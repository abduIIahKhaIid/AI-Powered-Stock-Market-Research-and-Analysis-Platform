"""Valuation metrics, earnings history and peer comparison (SCRUM-30).

Fundamentals come from the latest fiscal year in SEC filings; the price is the latest close.
Every metric carries its formula and the inputs it used, each with its source, so answers can
show the calculation (Detailed mode) and cite every cell.
"""

from __future__ import annotations

from typing import Any

from .market_data import PriceProvider, build_quote
from .sec import SOURCE_LABEL as SEC_SOURCE
from .sec import SecClient, SecError, build_statement, shares_outstanding

MAX_COMPARE = 5

METRICS: dict[str, tuple[str, str, str]] = {
    # key: (label, unit, formula)
    "price": ("Price", "USD", "latest close"),
    "market_cap": ("Market capitalisation", "USD", "price x shares outstanding"),
    "pe": ("P/E", "x", "price / diluted EPS (latest fiscal year)"),
    "ps": ("P/S", "x", "market cap / revenue (latest fiscal year)"),
    "ev_ebitda": (
        "EV/EBITDA",
        "x",
        "(market cap + long-term debt + short-term debt - cash) / "
        "(operating income + depreciation and amortization)",
    ),
    "gross_margin": ("Gross margin", "%", "gross profit / revenue x 100"),
    "operating_margin": ("Operating margin", "%", "operating income / revenue x 100"),
    "net_margin": ("Net margin", "%", "net income / revenue x 100"),
    "revenue_growth": (
        "Revenue growth, year on year",
        "%",
        "(revenue / prior-year revenue - 1) x 100",
    ),
    "eps_growth": ("Diluted EPS growth, year on year", "%", "(EPS / prior-year EPS - 1) x 100"),
}


class ValuationError(ValueError):
    pass


def _ratio(a: float | None, b: float | None, scale: float = 1.0) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b * scale


def fundamentals(sec: SecClient, symbol: str) -> dict[str, Any]:
    cik, name = sec.lookup(symbol)
    facts = sec.company_facts(cik)
    income = build_statement(facts, cik, "income", "annual", 2)["periods"]
    balance = build_statement(facts, cik, "balance", "annual", 1)["periods"][0]
    cash_flow = build_statement(facts, cik, "cash_flow", "annual", 1)["periods"][0]
    return {
        "cik": cik,
        "name": name,
        "income": income,
        "balance": balance,
        "cash_flow": cash_flow,
        "shares": shares_outstanding(facts, cik),
    }


def latest_price(prices: PriceProvider, symbol: str) -> dict[str, Any]:
    quote = build_quote(symbol, prices.history(symbol, period="5d", interval="1d"))
    return {"value": quote["price"], "as_of": quote["trading_day"], "source": prices.source}


def valuation_metrics(symbol: str, price: dict[str, Any], fund: dict[str, Any]) -> dict[str, Any]:
    latest, prior = fund["income"][0], (fund["income"][1] if len(fund["income"]) > 1 else None)
    inc, bal, cf = latest["values"], fund["balance"]["values"], fund["cash_flow"]["values"]
    shares = fund["shares"]

    def sec_input(key: str, period: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        return {
            "value": values.get(key),
            "period_end": period["end"],
            "form": period["form"],
            "link": period["link"],
            "source": SEC_SOURCE,
        }

    revenue = inc.get("revenue")
    gross = inc.get("gross_profit")
    if gross is None and revenue is not None and inc.get("cost_of_revenue") is not None:
        gross = revenue - inc["cost_of_revenue"]
    eps = inc.get("eps_diluted")
    market_cap = price["value"] * shares["value"] if shares else None
    debt = (bal.get("long_term_debt") or 0) + (bal.get("short_term_debt") or 0)
    ev = market_cap + debt - (bal.get("cash") or 0) if market_cap is not None else None
    ebitda = (
        inc["operating_income"] + cf["depreciation_amortization"]
        if inc.get("operating_income") is not None
        and cf.get("depreciation_amortization") is not None
        else None
    )
    prior_inc = prior["values"] if prior else {}

    values: dict[str, float | None] = {
        "price": price["value"],
        "market_cap": market_cap,
        "pe": _ratio(price["value"], eps) if eps and eps > 0 else None,
        "ps": _ratio(market_cap, revenue),
        "ev_ebitda": _ratio(ev, ebitda) if ebitda and ebitda > 0 else None,
        "gross_margin": _ratio(gross, revenue, 100),
        "operating_margin": _ratio(inc.get("operating_income"), revenue, 100),
        "net_margin": _ratio(inc.get("net_income"), revenue, 100),
        "revenue_growth": (
            (_ratio(revenue, prior_inc.get("revenue")) or 0) * 100 - 100
            if revenue and prior_inc.get("revenue")
            else None
        ),
        "eps_growth": (
            (eps / prior_inc["eps_diluted"] - 1) * 100
            if eps is not None and prior_inc.get("eps_diluted") and prior_inc["eps_diluted"] > 0
            else None
        ),
    }
    notes = []
    if eps is not None and eps <= 0:
        notes.append("P/E is not meaningful because diluted EPS is zero or negative.")
    if shares is None:
        notes.append("Shares outstanding were not found, so market-cap based metrics are missing.")
    if ebitda is None:
        notes.append("EBITDA could not be computed (operating income or D&A missing).")

    inputs = {
        "price": price,
        "shares_outstanding": {
            **(shares or {}),
            "source": SEC_SOURCE,
        },
        "revenue": sec_input("revenue", latest, inc),
        "gross_profit": {**sec_input("gross_profit", latest, inc), "value": gross},
        "operating_income": sec_input("operating_income", latest, inc),
        "net_income": sec_input("net_income", latest, inc),
        "eps_diluted": sec_input("eps_diluted", latest, inc),
        "long_term_debt": sec_input("long_term_debt", fund["balance"], bal),
        "short_term_debt": sec_input("short_term_debt", fund["balance"], bal),
        "cash": sec_input("cash", fund["balance"], bal),
        "depreciation_amortization": sec_input("depreciation_amortization", fund["cash_flow"], cf),
    }
    if prior:
        inputs["prior_revenue"] = sec_input("revenue", prior, prior_inc)
        inputs["prior_eps_diluted"] = sec_input("eps_diluted", prior, prior_inc)
    inputs["enterprise_value"] = {"value": ev, "formula": "market cap + debt - cash"}
    inputs["ebitda"] = {"value": ebitda, "formula": "operating income + D&A"}

    metrics = {
        key: {
            "label": label,
            "value": None if values[key] is None else round(values[key], 2),  # type: ignore[arg-type]
            "unit": unit,
            "formula": formula,
        }
        for key, (label, unit, formula) in METRICS.items()
    }
    if metrics["market_cap"]["value"] is not None:
        metrics["market_cap"]["value"] = round(market_cap or 0)
    return {
        "symbol": symbol,
        "name": fund["name"],
        "fiscal_year_end": latest["end"],
        "metrics": metrics,
        "inputs": inputs,
        "notes": notes,
        "url": latest["link"],
    }


def earnings_history(sec: SecClient, symbol: str) -> dict[str, Any]:
    cik, name = sec.lookup(symbol)
    facts = sec.company_facts(cik)

    def rows(freq: str, count: int) -> list[dict[str, Any]]:
        try:
            periods = build_statement(facts, cik, "income", freq, count)["periods"]
        except SecError:
            return []  # e.g. no quarterly filings in XBRL
        return [
            {
                "period_end": p["end"],
                "eps_diluted": p["values"].get("eps_diluted"),
                "eps_basic": p["values"].get("eps_basic"),
                "net_income": p["values"].get("net_income"),
                "form": p["form"],
                "filed": p["filed"],
                "link": p["link"],
            }
            for p in periods
        ]

    return {
        "symbol": symbol,
        "name": name,
        "cik": cik,
        "annual": rows("annual", 5),
        "quarterly": rows("quarterly", 8),
    }


def compare_table(results: dict[str, dict[str, Any] | str], metrics: list[str]) -> dict[str, Any]:
    """Rows of metrics, one cell per symbol, each cell with its own source."""
    rows = []
    for key in metrics:
        label, unit, formula = METRICS[key]
        cells: dict[str, Any] = {}
        for symbol, result in results.items():
            if isinstance(result, str):
                cells[symbol] = {"value": None, "error": result}
                continue
            price = result["inputs"]["price"]
            cells[symbol] = {
                "value": result["metrics"][key]["value"],
                "source": (
                    f"{price['source']} ({price['as_of']})"
                    if key == "price"
                    else f"{SEC_SOURCE}, fiscal year ending {result['fiscal_year_end']}"
                    + (
                        ""
                        if key not in {"market_cap", "pe", "ps", "ev_ebitda"}
                        else f"; price {price['as_of']}"
                    )
                ),
                "link": result["url"],
            }
        rows.append(
            {"metric": key, "label": label, "unit": unit, "formula": formula, "cells": cells}
        )
    return {"symbols": list(results), "rows": rows}


def parse_symbols(symbols: list[str]) -> list[str]:
    unique = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    if len(unique) < 2:
        raise ValuationError("Give at least two different symbols to compare.")
    if len(unique) > MAX_COMPARE:
        raise ValuationError(f"Compare at most {MAX_COMPARE} symbols at a time.")
    return unique


def parse_metrics(metrics: list[str] | None) -> list[str]:
    if not metrics:
        return list(METRICS)
    unknown = [m for m in metrics if m not in METRICS]
    if unknown:
        raise ValuationError(f"Unknown metrics: {', '.join(unknown)}. Use: {', '.join(METRICS)}.")
    return list(dict.fromkeys(metrics))
