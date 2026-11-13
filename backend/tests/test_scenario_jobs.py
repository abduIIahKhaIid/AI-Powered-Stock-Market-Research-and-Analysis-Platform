"""SCRUM-31 / SCRUM-75: scenario charts in the chat and sweeps as background jobs."""

from pathlib import Path
from typing import Any

import pytest

from stock_api.agent.job_tools import START_SWEEP, JobLauncher, JobToolbox
from stock_api.agent.toolbox import ToolOutcome, ToolSpec
from stock_api.chart_spec import chart_from_tool
from stock_api.jobs.registry import (
    JobInputError,
    build_registry,
    report_sweep,
    validate_sweep,
)
from stock_api.jobs.results import LocalResultStore
from stock_api.jobs.runner import execute
from stock_api.jobs.store import Job, MemoryJobStore


def scenario_payload(symbol: str, case: dict[str, Any]) -> dict[str, Any]:
    growth = case.get("revenue_growth", 5.0)
    value = round(100.0 + growth * 10, 2)
    return {
        "data": {
            "symbol": symbol,
            "name": f"{symbol} Inc.",
            "starting_point": {"price": 107.1},
            "chart": {
                "metric": "revenue",
                "unit": "USD",
                "base_year": 2024,
                "base_value": 400e9,
                "series": [
                    {"name": case.get("name", "base"), "points": [{"year": 2025, "value": 1}]}
                ],
            },
            "table": [
                {
                    "case": case.get("name", "base"),
                    "revenue_growth": growth,
                    "net_margin": 25.0,
                    "discount_rate": 9.0,
                    "final_year": 2029,
                    "final_revenue": 500e9,
                    "final_eps": 8.1,
                    "value_per_share": value,
                    "vs_price_pct": round((value / 107.1 - 1) * 100, 1),
                }
            ],
            "assumptions": [f"Starting point for {symbol}.", "Method: discounted net income."],
        },
        "source": "SEC EDGAR; Fake prices",
        "as_of": "2026-11-13",
    }


class Runner:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.failing = failing or set()

    def __call__(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append(arguments)
        if arguments["symbol"] in self.failing:
            return ToolOutcome.failure(name, arguments, f"{arguments['symbol']}: no SEC data")
        payload = scenario_payload(arguments["symbol"], arguments["cases"][0])
        return ToolOutcome(name, arguments, ok=True, payload=payload)


def test_scenario_results_become_a_chart() -> None:
    spec = chart_from_tool("run_scenario", scenario_payload("AAPL", {"name": "base"}))
    assert spec is not None
    assert (spec["kind"], spec["symbol"], spec["base_year"], spec["price"]) == (
        "scenario",
        "AAPL",
        2024,
        107.1,
    )
    assert spec["series"][0]["name"] == "base" and spec["table"][0]["value_per_share"] == 150.0
    assert chart_from_tool("run_scenario", {"data": {"chart": {}}}) is None


def test_validate_sweep_with_a_grid_and_with_cases() -> None:
    grid = validate_sweep(
        {"symbols": ["aapl"], "grid": {"revenue_growth": [2, 5], "net_margin": [20, 25, 30]}}
    )
    assert len(grid["cases"]) == 6
    assert grid["cases"][0] == {
        "revenue_growth": 2,
        "net_margin": 20,
        "name": "growth 2%, margin 20%",
    }
    cases = validate_sweep(
        {"symbols": ["AAPL", "MSFT"], "cases": [{"name": "slow", "revenue_growth": 1}]}
    )
    assert cases["cases"] == [{"name": "slow", "revenue_growth": 1}] and cases["assumptions"] == {}


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"symbols": [], "cases": [{}]}, "non-empty list"),
        ({"symbols": [f"S{i}" for i in range(6)], "cases": [{}]}, "at most 5 symbols"),
        ({"symbols": ["AAPL"]}, "Give cases"),
        ({"symbols": ["AAPL"], "grid": {"revenue_growth": list(range(26))}}, "At most 25"),
        ({"symbols": ["AAPL"], "grid": {"growth": [1]}}, "grid keys"),
        ({"symbols": ["AAPL"], "cases": [{"margin": 3}]}, "Unknown assumptions: margin"),
        ({"symbols": ["AAPL"], "cases": [{"net_margin": "high"}]}, "must be numbers"),
    ],
)
def test_validate_sweep_rejects(params: dict[str, Any], message: str) -> None:
    with pytest.raises(JobInputError, match=message):
        validate_sweep(params)


def test_sweep_runs_every_scenario_with_progress(tmp_path: Path) -> None:
    runner = Runner(failing={"MSFT"})
    registry = build_registry(runner)
    kind = registry["scenario_sweep"]
    store, results = MemoryJobStore(), LocalResultStore(tmp_path)
    params = kind.validate(
        {
            "symbols": ["AAPL", "MSFT"],
            "grid": {"revenue_growth": [2, 5, 8, 11]},
            "assumptions": {"discount_rate": 8},
        }
    )
    job = store.create(kind.name, params)
    stages: list[str] = []
    original = store.update

    def update(job_id: str, **changes: Any) -> Job:
        if "stage" in changes:
            stages.append(changes["stage"])
        return original(job_id, **changes)

    store.update = update  # type: ignore[method-assign]
    done = execute(job.id, store, registry, results)
    assert done.status == "succeeded", done.error
    assert (
        "Scenario 1 of 8: AAPL, growth 2%" in stages
        and "Scenario 5 of 8: MSFT, growth 2%" in stages
    )
    # MSFT fails once and is not tried again for every case.
    assert [c["symbol"] for c in runner.calls] == ["AAPL"] * 4 + ["MSFT"]
    assert runner.calls[0]["assumptions"] == {"discount_rate": 8}
    rows = done.result["rows"]
    assert [r["case"] for r in rows] == ["growth 2%", "growth 5%", "growth 8%", "growth 11%"]
    assert done.result["errors"] == {"MSFT": "MSFT: no SEC data"}
    assert done.summary == "4 scenarios for AAPL, MSFT"
    csv_lines = results.read(done.id, "scenario_sweep.csv").decode().splitlines()
    assert csv_lines[0].startswith("symbol,case,revenue_growth") and len(csv_lines) == 5

    report = report_sweep(params, done.result)
    assert "| AAPL | growth 11% | 210.00 | +96.1% |" in report
    assert "**MSFT**: MSFT: no SEC data" in report and "**Assumptions**" in report


class Toolbox:
    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec("run_scenario", "What-if")]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(name, arguments, ok=True, payload={})


class Queue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue(self, job: Job, kind: Any) -> None:
        self.enqueued.append(job.id)

    def revoke(self, job_id: str) -> None:
        pass


async def test_the_agent_can_start_a_sweep() -> None:
    store, queue, registry = MemoryJobStore(), Queue(), build_registry(Runner())
    launcher = JobLauncher(lambda: store, lambda: registry, queue)  # type: ignore[arg-type]
    toolbox = JobToolbox(Toolbox(), launcher, "c" * 32)
    assert START_SWEEP in [spec.name for spec in await toolbox.list_tools()]
    outcome = await toolbox.call(
        START_SWEEP, {"symbols": ["AAPL"], "grid": {"net_margin": [20, 25, 30, 35]}}
    )
    assert outcome.ok and outcome.payload["title"] == "Scenario sweep"
    assert queue.enqueued == [outcome.payload["job_id"]]
    bad = await toolbox.call(START_SWEEP, {"symbols": ["AAPL"]})
    assert not bad.ok and "Give cases" in (bad.error or "")
