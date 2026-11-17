"""Saving runs, finding the previous run and comparing the two."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).with_name("results")


def slug(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", label).strip("-").lower() or "run"


def save_run(run: dict[str, Any], results_dir: Path = RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = results_dir / f"{stamp}-{slug(run['meta']['model'])}.json"
    path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return path


def previous_run(
    model: str, results_dir: Path = RESULTS_DIR, exclude: Path | None = None
) -> tuple[Path, dict[str, Any]] | None:
    """The newest saved run of the same model (runs of other models are not comparable)."""
    if not results_dir.is_dir():
        return None
    for path in sorted(results_dir.glob("*.json"), reverse=True):
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if run.get("meta", {}).get("model") == model and run.get("meta", {}).get("full", True):
            return path, run
    return None


@dataclass
class Comparison:
    score_change: float
    pass_rate_change: float
    newly_failing: list[str] = field(default_factory=list)
    newly_passing: list[str] = field(default_factory=list)
    worse: list[tuple[str, float, float]] = field(default_factory=list)
    better: list[tuple[str, float, float]] = field(default_factory=list)


def compare(current: dict[str, Any], previous: dict[str, Any]) -> Comparison:
    before = {c["id"]: c for c in previous.get("cases", [])}
    comparison = Comparison(
        score_change=round(current["summary"]["score"] - previous["summary"]["score"], 4),
        pass_rate_change=round(
            current["summary"]["pass_rate"] - previous["summary"]["pass_rate"], 4
        ),
    )
    for case in current.get("cases", []):
        old = before.get(case["id"])
        if old is None:
            continue
        if old["passed"] and not case["passed"]:
            comparison.newly_failing.append(case["id"])
        elif case["passed"] and not old["passed"]:
            comparison.newly_passing.append(case["id"])
        delta = case["score"] - old["score"]
        if delta <= -0.01:
            comparison.worse.append((case["id"], old["score"], case["score"]))
        elif delta >= 0.01:
            comparison.better.append((case["id"], old["score"], case["score"]))
    return comparison


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _signed(value: float) -> str:
    return f"{value * 100:+.1f} points"


def markdown(run: dict[str, Any], comparison: Comparison | None, previous_name: str | None) -> str:
    summary, meta = run["summary"], run["meta"]
    lines = [
        f"## Eval results: {meta['model']}",
        "",
        f"Score **{_pct(summary['score'])}**, {summary['passed']} of {summary['cases']} cases "
        f"passed ({_pct(summary['pass_rate'])}). Safety failures: {summary['safety_failures']}. "
        f"Errors: {summary['errors']}.",
        "",
        "| Category | Cases | Passed | Score |",
        "|---|---|---|---|",
    ]
    for name, group in summary["categories"].items():
        lines.append(f"| {name} | {group['cases']} | {group['passed']} | {_pct(group['score'])} |")
    lines += ["", "| Check | Mean |", "|---|---|"]
    lines += [f"| {name} | {_pct(value)} |" for name, value in summary["checks"].items()]
    lines += [
        "",
        f"Time {summary['seconds']} s, {summary['llm_calls']} model calls, "
        f"{summary['tokens']} tokens, cost {summary['cost_usd']} USD.",
    ]
    if comparison is None:
        lines += ["", "No earlier run of this model to compare with."]
    else:
        lines += [
            "",
            f"Compared with {previous_name}: score {_signed(comparison.score_change)}, "
            f"pass rate {_signed(comparison.pass_rate_change)}.",
        ]
        if comparison.newly_failing:
            lines.append("Now failing: " + ", ".join(comparison.newly_failing) + ".")
        if comparison.newly_passing:
            lines.append("Now passing: " + ", ".join(comparison.newly_passing) + ".")
    failing = [c for c in run["cases"] if not c["passed"]]
    if failing:
        lines += ["", "| Failing case | Score | Why |", "|---|---|---|"]
        for case in failing:
            reasons = list(case.get("safety_problems", []))
            if case["missing_figures"]:
                reasons.append("missing " + ", ".join(case["missing_figures"]))
            reasons += [
                f"{k} {v:.2f}" for k, v in case["checks"].items() if v < 1 and k != "figures"
            ]
            why = case.get("error") or "; ".join(reasons)
            lines.append(f"| {case['id']} | {_pct(case['score'])} | {why} |")
    return "\n".join(lines) + "\n"
