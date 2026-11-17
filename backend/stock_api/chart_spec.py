"""Chart specs for the UI (SCRUM-36), built from tool results the agent already fetched."""

from __future__ import annotations

from typing import Any

CHART_TOOLS = {
    "get_price_history",
    "compute_indicators",
    "run_scenario",
    "get_financial_statements",
    "get_earnings",
    "compare_stocks",
}

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
    if name in ("get_financial_statements", "get_earnings"):
        return fundamentals_chart(name, payload, data)
    if name == "compare_stocks":
        return comparison_table(payload, data)
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
        "sources": [{"label": f"{payload.get('source')}, as of {payload.get('as_of')}"}],
        "assumptions": [
            "Prices are adjusted for splits and dividends."
            if data.get("adjusted")
            else "Prices are not adjusted for splits or dividends.",
            "Indicators are computed from the closing prices shown.",
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
        "sources": [
            {"label": "SEC filing for the starting fiscal year", "link": data.get("url")},
            {"label": f"{payload.get('source')}, as of {payload.get('as_of')}"},
        ],
        "assumptions": [str(line) for line in data.get("assumptions") or []],
    }


def _ratio(part: Any, whole: Any) -> float | None:
    if not isinstance(part, int | float) or not isinstance(whole, int | float) or not whole:
        return None
    return round(part / whole * 100, 2)


def _filing_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"label": f"{row['form']} for the period ending {row['end']}", "link": row.get("link")}
        for row in reversed(rows)
        if row.get("link")
    ]


def fundamentals_chart(
    name: str, payload: dict[str, Any], data: dict[str, Any]
) -> dict[str, Any] | None:
    """Revenue, net income, EPS and margins per period (SCRUM-37)."""
    derived: dict[str, str] = {}
    if name == "get_financial_statements":
        if data.get("statement") != "income" or not data.get("periods"):
            return None
        rows = []
        for period in sorted(data["periods"], key=lambda p: p["end"]):
            values = period.get("values") or {}
            revenue = values.get("revenue")
            gross = values.get("gross_profit")
            if gross is None and revenue is not None and values.get("cost_of_revenue") is not None:
                gross = revenue - values["cost_of_revenue"]
            rows.append(
                {
                    "end": period["end"],
                    "revenue": revenue,
                    "net_income": values.get("net_income"),
                    "operating_income": values.get("operating_income"),
                    "eps_diluted": values.get("eps_diluted"),
                    "gross_margin": _ratio(gross, revenue),
                    "operating_margin": _ratio(values.get("operating_income"), revenue),
                    "net_margin": _ratio(values.get("net_income"), revenue),
                    "form": period.get("form"),
                    "link": period.get("link"),
                }
            )
        freq = data.get("freq", "annual")
        derived = data.get("derived") or {}
    else:
        freq = "annual"
        rows = [
            {
                "end": row["period_end"],
                "net_income": row.get("net_income"),
                "eps_diluted": row.get("eps_diluted"),
                "form": row.get("form"),
                "link": row.get("link"),
            }
            for row in sorted(data.get("annual") or [], key=lambda r: r["period_end"])
        ]
        if not rows:
            return None
    assumptions = [
        "Figures as reported in each SEC filing (10-K for years, 10-Q for quarters), in USD; "
        "EPS in USD per share, diluted.",
        "Margins are each item divided by revenue for the same period, times 100.",
    ]
    assumptions += [
        f"{key.replace('_', ' ').capitalize()} = {formula}" for key, formula in derived.items()
    ]
    return {
        "kind": "fundamentals",
        "symbol": data.get("symbol"),
        "name": data.get("name"),
        "freq": freq,
        "rows": rows,
        "source": payload.get("source"),
        "as_of": payload.get("as_of"),
        "sources": _filing_sources(rows),
        "assumptions": assumptions,
    }


def comparison_table(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    """compare_stocks as a sortable table: one row per symbol, one column per metric."""
    symbols, rows = data.get("symbols") or [], data.get("rows") or []
    if not symbols or not rows:
        return None
    sources: dict[str, dict[str, Any]] = {}
    for row in rows:
        for cell in row["cells"].values():
            if cell.get("source"):
                sources.setdefault(
                    cell["source"], {"label": cell["source"], "link": cell.get("link")}
                )
    return {
        "kind": "comparison",
        "symbol": ",".join(symbols),
        "symbols": symbols,
        "metrics": [
            {"key": r["metric"], "label": r["label"], "unit": r["unit"], "formula": r["formula"]}
            for r in rows
        ],
        "values": {
            symbol: {
                r["metric"]: {
                    "value": r["cells"][symbol].get("value"),
                    "error": r["cells"][symbol].get("error"),
                }
                for r in rows
            }
            for symbol in symbols
        },
        "source": payload.get("source"),
        "as_of": payload.get("as_of"),
        "sources": list(sources.values()),
        "assumptions": [f"{r['label']} = {r['formula']}" for r in rows],
    }
