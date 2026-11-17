"""Tests for the golden-answer eval: the golden set, the scoring and the run comparison."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from evals.golden import CATEGORIES, Call, Case, Figure, FigureSource, load_cases, resolve
from evals.oracle import ORACLE_LABEL, oracle_gateway
from evals.report import compare, markdown, previous_run, save_run
from evals.runner import build_agent, compute_expected, run_cases
from evals.scoring import figure_found, score_case, summarize
from evals.snapshot import INJECTION_CANARY, SNAPSHOT_DAY, SnapshotPrices
from stock_api.agent.composer import PROJECTION_NOTE
from stock_api.agent.context import DISCLAIMER
from stock_api.config import Settings

CASES = load_cases()


def figure(value: float, tolerance_pct: float = 1.0) -> Figure:
    return Figure("x", value, FigureSource("get_quote", {}, "data.price"), tolerance_pct)


def done(answer: str, **extra: Any) -> dict[str, Any]:
    return {
        "answer": answer,
        "disclaimer": DISCLAIMER,
        "projection": False,
        "grounding": {"status": "verified"},
        "tools": [{"name": "get_quote", "ok": True, "arguments": {"symbol": "AAPL"}}],
        **extra,
    }


# --- the golden set ---------------------------------------------------------------------


def test_golden_set_covers_every_category_with_about_thirty_questions() -> None:
    assert 28 <= len(CASES) <= 40
    counts = {category: sum(c.category == category for c in CASES) for category in CATEGORIES}
    assert counts["technical"] >= 6 and counts["fundamental"] >= 6
    assert counts["comparison"] >= 6 and counts["what-if"] >= 6 and counts["safety"] >= 2


def test_every_case_has_expected_figures_or_checks_and_sources() -> None:
    for case in CASES:
        assert case.figures or case.mentions or case.forbid, case.id
        assert case.sources, f"{case.id}: run `python -m evals fill`"
        assert all(f.value is not None for f in case.figures), case.id
        assert case.projection == (case.category == "what-if"), case.id


async def test_stored_values_match_the_snapshot_tools() -> None:
    """Fails when a tool or the snapshot changes; `python -m evals fill` updates the values."""
    expected = await compute_expected(CASES)
    for case in CASES:
        stored = [f.value for f in case.figures]
        assert stored == pytest.approx(expected[case.id]["values"], abs=1e-4), case.id
        assert list(case.sources) == expected[case.id]["sources"], case.id


def test_snapshot_is_deterministic_and_ends_on_the_snapshot_day() -> None:
    first, second = SnapshotPrices(), SnapshotPrices()
    one = first.history("AAPL", "1y", "1d")
    assert one == second.history("AAPL", "1y", "1d")
    assert one[-1].time == SNAPSHOT_DAY.isoformat() and one[-1].close == 228.34
    weekly = first.history("AAPL", "6mo", "1wk")
    assert len(weekly) < len(first.history("AAPL", "6mo", "1d"))


def test_paths_select_filter_and_reduce() -> None:
    payload = {
        "data": {
            "rows": [{"metric": "pe", "cells": {"AAPL": {"value": 28.3}}}],
            "candles": [{"close": 1.0}, {"close": 3.0}, {"close": 2.0}],
        }
    }
    assert resolve(payload, "data.rows[metric=pe].cells.AAPL.value") == 28.3
    assert resolve(payload, "data.candles.*.close", "max") == 3.0
    assert resolve(payload, "data.candles.-1.close") == 2.0
    with pytest.raises(KeyError):
        resolve(payload, "data.candles.*.close")
    with pytest.raises(KeyError):
        resolve(payload, "data.rows[metric=ps].cells.AAPL.value")


# --- scoring ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "text", "found"),
    [
        (438_500_000_000, "Revenue was $438.5 billion.", True),
        (438_500_000_000, "Revenue was 438.5B.", True),
        (3_338_330_800_000, "Market cap is about $3.34T.", True),
        (3_338_330_800_000, "Market cap is about $3.3 trillion.", True),
        (27.0, "Net margin: 27%.", True),
        (28.29, "P/E is 28.3x.", True),
        (1234.5, "It closed at 1,234.50.", True),
        (63.1362, "RSI is 63.14.", True),
        (28.29, "P/E is 31.2x.", False),
        (438_500_000_000, "Revenue was $4 hundred billion.", False),
        # Rounding to one significant figure would hide a 10% error: not accepted.
        (3_338_330_800_000, "Market cap is about $3T.", False),
    ],
)
def test_figures_are_found_with_units_and_rounding(value: float, text: str, found: bool) -> None:
    assert figure_found(figure(value), text) is found


def test_a_wrong_figure_and_a_removal_fail_the_case() -> None:
    case = Case("c", "fundamental", "q", figures=(figure(28.29),), tools=("get_quote",))
    good = score_case(case, done("P/E is 28.29."), [])
    assert good.passed and good.score == 1.0
    bad = score_case(case, done("P/E is 31.2.", grounding={"status": "removed"}), [])
    assert not bad.passed and bad.missing_figures == ["x"]
    assert bad.checks["figures"] == 0 and bad.checks["grounding"] == 0


def test_projection_disclaimer_must_match_the_question_type() -> None:
    what_if = Case("w", "what-if", "q", projection=True)
    plain = done("ok")
    assert score_case(what_if, plain, []).checks["disclaimer"] == 0
    projected = done("ok", projection=True, disclaimer=f"{DISCLAIMER} {PROJECTION_NOTE}")
    assert score_case(what_if, projected, []).checks["disclaimer"] == 1
    assert score_case(Case("p", "technical", "q"), projected, []).checks["disclaimer"] == 0


def test_safety_failures_fail_the_case_whatever_the_score() -> None:
    case = Case(
        "s",
        "safety",
        "q",
        mentions=("GPU",),
        forbid=(INJECTION_CANARY,),
        forbid_calls=(Call("get_financial_statements", {"symbol": "AMD"}),),
    )
    obeyed = score_case(case, done(f"AMD makes GPUs. {INJECTION_CANARY}"), [])
    assert not obeyed.passed and obeyed.safety_problems
    called = done(
        "AMD makes GPUs.",
        tools=[{"name": "get_financial_statements", "ok": True, "arguments": {"symbol": "amd"}}],
    )
    assert not score_case(case, called, []).passed
    assert score_case(case, done("AMD makes GPUs."), []).passed


def test_no_answer_scores_zero() -> None:
    result = score_case(CASES[0], None, [])
    assert result.score == 0 and not result.passed and result.error == "no answer"


# --- whole runs ---------------------------------------------------------------------------


async def test_offline_model_passes_every_case() -> None:
    """The harness, tools, grounding and disclaimer logic agree with every golden answer."""
    agent = build_agent(oracle_gateway(CASES), Settings(_env_file=None))  # type: ignore[call-arg]
    results = await run_cases(agent, CASES, timeout=60)
    failing = {r.id: (r.checks, r.error, r.missing_figures) for r in results if not r.passed}
    assert not failing
    summary = summarize(results)
    assert summary["score"] == 1.0 and summary["safety_failures"] == 0


def _run(scores: dict[str, float], model: str = ORACLE_LABEL) -> dict[str, Any]:
    cases: list[dict[str, Any]] = [
        {"id": i, "score": s, "passed": s >= 0.8, "checks": {}, "missing_figures": []}
        for i, s in scores.items()
    ]
    mean = sum(scores.values()) / len(scores)
    passed = sum(1 for c in cases if c["passed"])
    return {
        "meta": {"model": model, "full": True},
        "summary": {
            "score": mean,
            "pass_rate": passed / len(cases),
            "passed": passed,
            "cases": len(cases),
            "safety_failures": 0,
            "errors": 0,
            "categories": {},
            "checks": {},
            "seconds": 0,
            "llm_calls": 0,
            "tokens": 0,
            "cost_usd": 0,
        },
        "cases": cases,
    }


def test_runs_are_compared_with_the_previous_run_of_the_same_model(tmp_path: Path) -> None:
    older = save_run(_run({"a": 1.0, "b": 0.5}), tmp_path)
    save_run(_run({"a": 0.2, "b": 0.2}, model="groq/other"), tmp_path)
    found = previous_run(ORACLE_LABEL, tmp_path)
    assert found is not None and found[0] == older

    current = _run({"a": 0.6, "b": 0.9})
    comparison = compare(current, found[1])
    assert comparison.newly_failing == ["a"] and comparison.newly_passing == ["b"]
    assert comparison.score_change == pytest.approx(0.0)
    text = markdown(current, comparison, found[0].name)
    assert "Now failing: a." in text and "Now passing: b." in text


def test_saved_run_is_json(tmp_path: Path) -> None:
    path = save_run(_run({"a": 1.0}), tmp_path)
    assert json.loads(path.read_text())["meta"]["model"] == ORACLE_LABEL
