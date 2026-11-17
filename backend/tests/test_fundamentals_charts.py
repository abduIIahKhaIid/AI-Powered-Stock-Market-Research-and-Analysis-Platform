"""SCRUM-37: chart specs for fundamentals and the comparison table."""

from typing import Any

from stock_api.chart_spec import chart_from_tool

LINK = "https://www.sec.gov/Archives/edgar/data/320193/{}/"


def statement(periods: list[dict[str, Any]], statement: str = "income") -> dict[str, Any]:
    return {
        "data": {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "statement": statement,
            "freq": "annual",
            "derived": {"free_cash_flow": "operating cash flow - capital expenditure"},
            "periods": periods,
        },
        "source": "SEC EDGAR company facts (XBRL)",
        "as_of": "2025-11-01",
    }


def period(end: str, revenue: float, cost: float, operating: float, net: float, eps: float) -> Any:
    return {
        "end": end,
        "form": "10-K",
        "link": LINK.format(end),
        "values": {
            "revenue": revenue,
            "cost_of_revenue": cost,
            "operating_income": operating,
            "net_income": net,
            "eps_diluted": eps,
        },
    }


def test_income_statement_becomes_a_fundamentals_chart() -> None:
    payload = statement(
        [
            period("2025-09-27", 400e9, 220e9, 120e9, 100e9, 6.5),
            period("2024-09-28", 380e9, 215e9, 110e9, 95e9, 6.0),
        ]
    )
    spec = chart_from_tool("get_financial_statements", payload)
    assert spec is not None and spec["kind"] == "fundamentals" and spec["symbol"] == "AAPL"
    assert [row["end"] for row in spec["rows"]] == ["2024-09-28", "2025-09-27"]  # oldest first
    latest = spec["rows"][1]
    assert (latest["gross_margin"], latest["operating_margin"], latest["net_margin"]) == (
        45.0,
        30.0,
        25.0,
    )
    assert latest["eps_diluted"] == 6.5
    assert spec["sources"][0] == {
        "label": "10-K for the period ending 2025-09-27",
        "link": LINK.format("2025-09-27"),
    }
    assert any(
        line.startswith("Margins are each item divided by revenue") for line in spec["assumptions"]
    )
    assert "Free cash flow = operating cash flow - capital expenditure" in spec["assumptions"]


def test_only_income_statements_and_earnings_are_charted() -> None:
    assert chart_from_tool("get_financial_statements", statement([], "balance")) is None
    earnings = {
        "data": {
            "symbol": "AAPL",
            "name": "Apple Inc.",
            "annual": [
                {
                    "period_end": "2025-09-27",
                    "eps_diluted": 6.5,
                    "net_income": 100e9,
                    "form": "10-K",
                    "link": "x",
                },
                {
                    "period_end": "2024-09-28",
                    "eps_diluted": 6.0,
                    "net_income": 95e9,
                    "form": "10-K",
                    "link": "y",
                },
            ],
        },
        "source": "SEC EDGAR",
        "as_of": "2025-11-01",
    }
    spec = chart_from_tool("get_earnings", earnings)
    assert spec is not None and [row["eps_diluted"] for row in spec["rows"]] == [6.0, 6.5]
    assert chart_from_tool("get_earnings", {"data": {"annual": []}}) is None


def test_compare_stocks_becomes_a_sortable_table_spec() -> None:
    cells = {
        "AAPL": {"value": 35.2, "source": "SEC EDGAR, fiscal year ending 2025-09-27", "link": "a"},
        "MSFT": {"value": None, "error": "MSFT: no SEC data"},
    }
    payload = {
        "data": {
            "symbols": ["AAPL", "MSFT"],
            "rows": [
                {
                    "metric": "pe",
                    "label": "P/E",
                    "unit": "x",
                    "formula": "price / diluted EPS",
                    "cells": cells,
                }
            ],
        },
        "source": "SEC EDGAR; latest closing prices",
        "as_of": "2026-11-17",
    }
    spec = chart_from_tool("compare_stocks", payload)
    assert spec is not None and spec["kind"] == "comparison" and spec["symbol"] == "AAPL,MSFT"
    assert spec["metrics"] == [
        {"key": "pe", "label": "P/E", "unit": "x", "formula": "price / diluted EPS"}
    ]
    assert spec["values"]["AAPL"]["pe"] == {"value": 35.2, "error": None}
    assert spec["values"]["MSFT"]["pe"]["error"] == "MSFT: no SEC data"
    assert spec["sources"] == [{"label": "SEC EDGAR, fiscal year ending 2025-09-27", "link": "a"}]
    assert spec["assumptions"] == ["P/E = price / diluted EPS"]


def test_price_and_scenario_specs_carry_sources_and_assumptions() -> None:
    price = chart_from_tool(
        "get_price_history",
        {
            "data": {
                "symbol": "AAPL",
                "candles": [{"time": "2026-11-17", "close": 1}],
                "adjusted": False,
            },
            "source": "Yahoo",
            "as_of": "2026-11-17",
        },
    )
    assert price is not None and price["sources"] == [{"label": "Yahoo, as of 2026-11-17"}]
    assert price["assumptions"][0] == "Prices are not adjusted for splits or dividends."
    scenario = chart_from_tool(
        "run_scenario",
        {
            "data": {
                "symbol": "AAPL",
                "url": "https://sec",
                "assumptions": ["Base case: growth 3%"],
                "chart": {"series": [{"name": "base", "points": []}], "base_year": 2026},
            },
            "source": "SEC; Yahoo",
            "as_of": "2026-11-17",
        },
    )
    assert scenario is not None and scenario["assumptions"] == ["Base case: growth 3%"]
    assert scenario["sources"][0]["link"] == "https://sec"
