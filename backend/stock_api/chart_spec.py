"""Chart specs for the UI (SCRUM-36), built from tool results the agent already fetched."""

from __future__ import annotations

from typing import Any

CHART_TOOLS = {"get_price_history"}


def chart_from_tool(name: str, payload: Any) -> dict[str, Any] | None:
    """A price chart spec from a get_price_history result, or None for other tools."""
    if name not in CHART_TOOLS or not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
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
    }
