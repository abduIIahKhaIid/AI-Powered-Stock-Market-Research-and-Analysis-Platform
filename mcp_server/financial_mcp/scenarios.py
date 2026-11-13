"""What-if projections with base, bull and bear cases (SCRUM-31, SCRUM-74).

The starting point is the latest fiscal year in SEC filings (revenue, net income, shares
outstanding) and the latest close. Each case grows revenue at a fixed yearly rate, applies a
net margin, and discounts the projected net income, plus a terminal value, back to today to
give a simple DCF-style value per share. Net income stands in for free cash flow; that and
every other assumption is returned with the result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from .sec import SOURCE_LABEL as SEC_SOURCE

MAX_INLINE_CASES = 3
MAX_SWEEP_CASES = 25
DEFAULT_DISCOUNT = 9.0
DEFAULT_TERMINAL = 2.5
DEFAULT_HORIZON = 5
# How far bull and bear move from the base case, in percentage points.
SPREAD = {"revenue_growth": 3.0, "net_margin": 2.0, "discount_rate": 1.0}

FIELDS = ("revenue_growth", "net_margin", "discount_rate", "terminal_growth", "horizon_years")
LIMITS: dict[str, tuple[float, float]] = {
    "revenue_growth": (-50.0, 100.0),
    "net_margin": (-100.0, 100.0),
    "discount_rate": (0.5, 30.0),
    "terminal_growth": (-5.0, 5.0),
    "horizon_years": (1, 10),
}
LABELS = {
    "revenue_growth": "Revenue growth",
    "net_margin": "Net margin",
    "discount_rate": "Discount rate",
    "terminal_growth": "Terminal growth",
    "horizon_years": "Horizon",
}


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True)
class Assumptions:
    revenue_growth: float  # percent a year
    net_margin: float  # percent of revenue
    discount_rate: float  # percent a year
    terminal_growth: float  # percent a year after the horizon
    horizon_years: int


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScenarioError(f"{name} must be a number (percent, for example 8 for 8%).")
    low, high = LIMITS[name]
    if not low <= value <= high:
        unit = "years" if name == "horizon_years" else "%"
        raise ScenarioError(f"{name} must be between {low:g} and {high:g} {unit}.")
    return float(value)


def starting_point(fund: dict[str, Any], price: dict[str, Any]) -> dict[str, Any]:
    """Revenue, net income and shares from the latest fiscal year, with their sources."""
    latest = fund["income"][0]
    values = latest["values"]
    revenue, net_income = values.get("revenue"), values.get("net_income")
    shares = (fund.get("shares") or {}).get("value")
    missing = [
        name
        for name, value in (
            ("revenue", revenue),
            ("net income", net_income),
            ("shares outstanding", shares),
        )
        if not value
    ]
    if missing:
        raise ScenarioError(f"The latest SEC filing has no {', '.join(missing)} for this company.")
    prior = fund["income"][1]["values"] if len(fund["income"]) > 1 else {}
    growth = (revenue / prior["revenue"] - 1) * 100 if prior.get("revenue") else None
    return {
        "fiscal_year_end": latest["end"],
        "revenue": revenue,
        "net_income": net_income,
        "shares_outstanding": shares,
        "price": price["value"],
        "price_as_of": price["as_of"],
        "historical_revenue_growth": None if growth is None else round(growth, 2),
        "historical_net_margin": round(net_income / revenue * 100, 2),
        "sources": {
            "fundamentals": {"source": SEC_SOURCE, "form": latest["form"], "link": latest["link"]},
            "price": {"source": price["source"], "as_of": price["as_of"]},
        },
    }


def base_assumptions(
    given: dict[str, Any] | None, start: dict[str, Any]
) -> tuple[Assumptions, dict[str, str]]:
    """The base case and where each value came from: the user, history or a default."""
    given = dict(given or {})
    unknown = sorted(set(given) - set(FIELDS))
    if unknown:
        raise ScenarioError(f"Unknown assumptions: {', '.join(unknown)}. Use {', '.join(FIELDS)}.")
    origin: dict[str, str] = {}

    def pick(name: str, fallback: float | None, fallback_origin: str) -> float:
        if given.get(name) is not None:
            origin[name] = "given"
            return _number(name, given[name])
        if fallback is None:
            raise ScenarioError(f"Give {name}: there is no history to start from.")
        origin[name] = fallback_origin
        low, high = LIMITS[name]
        return float(min(max(fallback, low), high))

    base = Assumptions(
        revenue_growth=pick(
            "revenue_growth", start["historical_revenue_growth"], "last fiscal year's growth"
        ),
        net_margin=pick("net_margin", start["historical_net_margin"], "last fiscal year's margin"),
        discount_rate=pick("discount_rate", DEFAULT_DISCOUNT, "default"),
        terminal_growth=pick("terminal_growth", DEFAULT_TERMINAL, "default"),
        horizon_years=int(pick("horizon_years", DEFAULT_HORIZON, "default")),
    )
    if base.discount_rate <= base.terminal_growth:
        raise ScenarioError("discount_rate must be higher than terminal_growth.")
    return base, origin


def build_cases(
    base: Assumptions, overrides: list[dict[str, Any]] | None, limit: int = MAX_INLINE_CASES
) -> list[tuple[str, Assumptions]]:
    """Base, bull and bear by default; otherwise each override applied to the base case."""
    if not overrides:
        bull = replace(
            base,
            revenue_growth=base.revenue_growth + SPREAD["revenue_growth"],
            net_margin=base.net_margin + SPREAD["net_margin"],
            discount_rate=max(
                base.terminal_growth + 0.5, base.discount_rate - SPREAD["discount_rate"]
            ),
        )
        bear = replace(
            base,
            revenue_growth=base.revenue_growth - SPREAD["revenue_growth"],
            net_margin=base.net_margin - SPREAD["net_margin"],
            discount_rate=base.discount_rate + SPREAD["discount_rate"],
        )
        return [("base", base), ("bull", bull), ("bear", bear)]
    if len(overrides) > limit:
        raise ScenarioError(
            f"At most {limit} scenarios at once here; run larger sweeps with "
            "start_job_scenario_sweep."
        )
    cases = []
    for index, override in enumerate(overrides):
        if not isinstance(override, dict):
            raise ScenarioError("Each case must be an object of assumption overrides.")
        name = str(override.get("name") or f"case {index + 1}")[:40]
        changes = {k: v for k, v in override.items() if k != "name"}
        unknown = sorted(set(changes) - set(FIELDS))
        if unknown:
            raise ScenarioError(f"Unknown assumptions in {name}: {', '.join(unknown)}.")
        values = asdict(base) | {k: _number(k, v) for k, v in changes.items()}
        values["horizon_years"] = int(values["horizon_years"])
        case = Assumptions(**values)
        if case.discount_rate <= case.terminal_growth:
            raise ScenarioError(f"{name}: discount_rate must be higher than terminal_growth.")
        cases.append((name, case))
    return cases


def project(start: dict[str, Any], name: str, a: Assumptions) -> dict[str, Any]:
    first_year = int(str(start["fiscal_year_end"])[:4])
    g, m, r, tg = (
        a.revenue_growth / 100,
        a.net_margin / 100,
        a.discount_rate / 100,
        a.terminal_growth / 100,
    )
    shares = start["shares_outstanding"]
    revenue = start["revenue"]
    present_value = 0.0
    years = []
    net_income = 0.0
    for t in range(1, a.horizon_years + 1):
        revenue *= 1 + g
        net_income = revenue * m
        discounted = net_income / (1 + r) ** t
        present_value += discounted
        years.append(
            {
                "year": first_year + t,
                "revenue": round(revenue),
                "net_income": round(net_income),
                "eps": round(net_income / shares, 2),
                "present_value": round(discounted),
            }
        )
    terminal = net_income * (1 + tg) / (r - tg)
    terminal_pv = terminal / (1 + r) ** a.horizon_years
    equity = present_value + terminal_pv
    per_share = equity / shares
    upside = (per_share / start["price"] - 1) * 100 if start["price"] else None
    return {
        "name": name,
        "assumptions": asdict(a),
        "years": years,
        "terminal_value": round(terminal),
        "terminal_present_value": round(terminal_pv),
        "equity_value": round(equity),
        "value_per_share": round(per_share, 2),
        "vs_price_pct": None if upside is None else round(upside, 1),
        "meaningful": per_share > 0,
    }


def _pct(value: float) -> str:
    return f"{value:.1f}%"


def assumption_lines(
    start: dict[str, Any], cases: list[dict[str, Any]], origin: dict[str, str]
) -> list[str]:
    fy = str(start["fiscal_year_end"])[:4]
    lines = [
        f"Starting point: fiscal year {fy} revenue {start['revenue']:,.0f} USD and net income "
        f"{start['net_income']:,.0f} USD from SEC filings; {start['shares_outstanding']:,.0f} "
        f"shares outstanding, held constant; price {start['price']} USD on "
        f"{start['price_as_of']}.",
    ]
    for case in cases:
        a = case["assumptions"]
        lines.append(
            f"{case['name'].capitalize()} case: revenue growth {_pct(a['revenue_growth'])} a year, "
            f"net margin {_pct(a['net_margin'])}, discount rate {_pct(a['discount_rate'])}, "
            f"terminal growth {_pct(a['terminal_growth'])}, {a['horizon_years']} years."
        )
    sources = ", ".join(f"{LABELS[k].lower()} from {v}" for k, v in origin.items() if v != "given")
    if sources:
        lines.append(f"Base values not given by you: {sources}.")
    lines.append(
        "Method: projected net income stands in for free cash flow; each year is discounted at "
        "the discount rate, plus a terminal value growing at the terminal growth rate."
    )
    return lines


def run_scenarios(
    symbol: str,
    name: str,
    start: dict[str, Any],
    given: dict[str, Any] | None,
    overrides: list[dict[str, Any]] | None,
    limit: int = MAX_INLINE_CASES,
) -> dict[str, Any]:
    base, origin = base_assumptions(given, start)
    results = [project(start, case_name, a) for case_name, a in build_cases(base, overrides, limit)]
    notes = []
    if any(not c["meaningful"] for c in results):
        notes.append(
            "A negative value per share means projected net income is negative; it is not a "
            "meaningful valuation."
        )
    return {
        "symbol": symbol,
        "name": name,
        "starting_point": start,
        "cases": results,
        "chart": {
            "metric": "revenue",
            "unit": "USD",
            "base_year": int(str(start["fiscal_year_end"])[:4]),
            "base_value": start["revenue"],
            "series": [
                {
                    "name": c["name"],
                    "points": [{"year": y["year"], "value": y["revenue"]} for y in c["years"]],
                }
                for c in results
            ],
        },
        "table": [
            {
                "case": c["name"],
                "revenue_growth": c["assumptions"]["revenue_growth"],
                "net_margin": c["assumptions"]["net_margin"],
                "discount_rate": c["assumptions"]["discount_rate"],
                "final_year": c["years"][-1]["year"],
                "final_revenue": c["years"][-1]["revenue"],
                "final_eps": c["years"][-1]["eps"],
                "value_per_share": c["value_per_share"],
                "vs_price_pct": c["vs_price_pct"],
            }
            for c in results
        ],
        "assumptions": assumption_lines(start, results, origin),
        "notes": notes,
        "url": start["sources"]["fundamentals"]["link"],
    }
