"""SCRUM-31 / SCRUM-74: projections with base, bull and bear cases."""

from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from test_valuation import UA, PricesWithCalendar, fetch

from financial_mcp.scenarios import (
    Assumptions,
    ScenarioError,
    base_assumptions,
    build_cases,
    project,
)
from financial_mcp.sec import RateLimiter, SecClient
from financial_mcp.server import mcp
from financial_mcp.services import Services, set_services

START = {
    "fiscal_year_end": "2024-09-28",
    "revenue": 400e9,
    "net_income": 100e9,
    "shares_outstanding": 15e9,
    "price": 107.1,
    "price_as_of": "2026-11-11",
    "historical_revenue_growth": 5.26,
    "historical_net_margin": 25.0,
    "sources": {"fundamentals": {"link": "https://www.sec.gov/x"}, "price": {}},
}


def test_projection_matches_the_formula() -> None:
    a = Assumptions(10.0, 20.0, 10.0, 2.0, 2)
    case = project(START, "base", a)
    rev1, rev2 = 400e9 * 1.1, 400e9 * 1.1**2
    ni1, ni2 = rev1 * 0.2, rev2 * 0.2
    pv = ni1 / 1.1 + ni2 / 1.1**2
    terminal = ni2 * 1.02 / (0.10 - 0.02)
    equity = pv + terminal / 1.1**2
    assert [y["year"] for y in case["years"]] == [2025, 2026]
    assert case["years"][1]["revenue"] == round(rev2)
    assert case["years"][1]["eps"] == round(ni2 / 15e9, 2)
    assert case["terminal_value"] == round(terminal)
    assert case["value_per_share"] == round(equity / 15e9, 2)
    assert case["vs_price_pct"] == round((equity / 15e9 / 107.1 - 1) * 100, 1)


def test_defaults_come_from_history_and_are_labelled() -> None:
    base, origin = base_assumptions({"discount_rate": 8}, START)
    assert base == Assumptions(5.26, 25.0, 8.0, 2.5, 5)
    assert origin == {
        "revenue_growth": "last fiscal year's growth",
        "net_margin": "last fiscal year's margin",
        "discount_rate": "given",
        "terminal_growth": "default",
        "horizon_years": "default",
    }


def test_bull_and_bear_move_by_the_spread() -> None:
    base = Assumptions(5.0, 25.0, 9.0, 2.5, 5)
    cases = dict(build_cases(base, None))
    assert cases["bull"] == Assumptions(8.0, 27.0, 8.0, 2.5, 5)
    assert cases["bear"] == Assumptions(2.0, 23.0, 10.0, 2.5, 5)


@pytest.mark.parametrize(
    ("given", "cases", "message"),
    [
        ({"revenue_growth": 500}, None, "between -50 and 100"),
        ({"discount_rate": "high"}, None, "must be a number"),
        ({"discount_rate": 2, "terminal_growth": 3}, None, "higher than terminal_growth"),
        ({"cagr": 5}, None, "Unknown assumptions: cagr"),
        (None, [{"name": f"c{i}"} for i in range(4)], "start_job_scenario_sweep"),
        (None, [{"name": "x", "margin": 5}], "Unknown assumptions in x"),
    ],
)
def test_bad_assumptions_are_explained(
    given: dict[str, Any] | None, cases: list[dict[str, Any]] | None, message: str
) -> None:
    with pytest.raises(ScenarioError, match=message):
        base, _ = base_assumptions(given, START)
        build_cases(base, cases)


@pytest.fixture
def services(directory: Any, tmp_path: Path) -> Any:
    sec = SecClient(UA, tmp_path, fetcher=fetch, limiter=RateLimiter(interval=0.0))
    set_services(Services(directory=directory, prices=PricesWithCalendar(), sec=sec))
    yield
    set_services(None)


async def call(name: str, arguments: dict[str, Any]) -> Any:
    result = await mcp.call_tool(name, arguments)
    return getattr(result, "structured_content", None)


async def test_run_scenario_tool(services: None) -> None:
    body = await call("run_scenario", {"symbol": "AAPL", "assumptions": {"horizon_years": 3}})
    data = body["data"]
    assert [c["name"] for c in data["cases"]] == ["base", "bull", "bear"]
    base = data["cases"][0]
    assert base["assumptions"]["revenue_growth"] == 5.26 and base["assumptions"]["net_margin"] == 25
    assert len(base["years"]) == 3 and base["years"][0]["year"] == 2025
    assert [s["name"] for s in data["chart"]["series"]] == ["base", "bull", "bear"]
    assert data["chart"]["base_year"] == 2024 and data["chart"]["base_value"] == 400e9
    bull, bear = data["table"][1], data["table"][2]
    assert bull["value_per_share"] > data["table"][0]["value_per_share"] > bear["value_per_share"]
    assert data["assumptions"][0].startswith("Starting point: fiscal year 2024 revenue")
    assert "Base case: revenue growth 5.3% a year" in data["assumptions"][1]
    assert any(line.startswith("Method:") for line in data["assumptions"])
    assert body["source"].startswith("SEC EDGAR") and body["as_of"] == "2026-11-11"


async def test_custom_cases_and_errors(services: None) -> None:
    cases = [{"name": "slow growth", "revenue_growth": 1}, {"name": "fast", "revenue_growth": 15}]
    data = (await call("run_scenario", {"symbol": "AAPL", "cases": cases}))["data"]
    assert [c["name"] for c in data["cases"]] == ["slow growth", "fast"]
    assert data["cases"][0]["assumptions"]["net_margin"] == 25

    # NVIDIA's fixture has one fiscal year only, so there is no growth history to start from.
    with pytest.raises(ToolError, match="NVDA: Give revenue_growth"):
        await mcp.call_tool("run_scenario", {"symbol": "NVDA"})
    loss = await call("run_scenario", {"symbol": "NVDA", "assumptions": {"revenue_growth": 5}})
    assert loss["data"]["cases"][0]["value_per_share"] < 0
    assert "not a meaningful valuation" in loss["data"]["notes"][0]
