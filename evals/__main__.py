"""Command line for the golden-answer eval (SCRUM-39). Run from the repository root:

    python -m evals                         # offline model: checks harness, tools and scoring
    python -m evals --model configured      # the LLM from .env (LLM_* settings)
    python -m evals --cases fund-aapl-pe,cmp-ps --model configured
    python -m evals fill                    # recompute expected figures in golden.json

Each run is saved in evals/results/ and compared with the previous run of the same model.
The exit code is 1 when the score is under --min-score, a safety case fails, or the score
dropped more than --max-drop since the previous run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from stock_api.config import Settings
from stock_api.llm import build_gateway

from .golden import GOLDEN_PATH, load_cases
from .oracle import ORACLE_LABEL, oracle_gateway
from .report import RESULTS_DIR, compare, markdown, previous_run, save_run
from .runner import build_agent, compute_expected, run_cases
from .scoring import CaseResult, summarize
from .snapshot import SNAPSHOT_DAY


def _git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _print_result(result: CaseResult) -> None:
    mark = "PASS" if result.passed else "FAIL"
    detail = result.error or ", ".join(f"{k} {v:.2f}" for k, v in result.checks.items())
    print(f"  {mark} {result.score * 100:5.1f}%  {result.id:<24} {detail}", flush=True)


def run(args: argparse.Namespace) -> int:
    cases = load_cases()
    if args.cases:
        wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
        unknown = wanted - {c.id for c in cases}
        if unknown:
            print(f"Unknown case ids: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        cases = [c for c in cases if c.id in wanted]
    if args.category:
        cases = [c for c in cases if c.category == args.category]
    if not cases:
        print("No cases to run.", file=sys.stderr)
        return 2

    settings = Settings()
    if args.model == "offline":
        gateway, label = oracle_gateway(load_cases()), ORACLE_LABEL
    else:
        gateway = build_gateway(settings)
        label = f"{settings.llm_provider}/{settings.llm_model}"
    print(f"Running {len(cases)} cases with {label} (snapshot {SNAPSHOT_DAY})", flush=True)

    agent = build_agent(gateway, settings)
    results = asyncio.run(
        run_cases(
            agent, cases, timeout=args.case_timeout, delay=args.delay, on_result=_print_result
        )
    )
    full = len(cases) == len(load_cases())
    run_data: dict[str, Any] = {
        "meta": {
            "model": label,
            "commit": _git_commit(),
            "snapshot_day": SNAPSHOT_DAY.isoformat(),
            "full": full,
            "cases": [c.id for c in cases],
        },
        "summary": summarize(results),
        "cases": [r.to_dict() for r in results],
    }

    results_dir = Path(args.results_dir)
    found = previous_run(label, results_dir) if full else None
    comparison = compare(run_data, found[1]) if found else None
    saved = save_run(run_data, results_dir) if not args.no_save else None
    report = markdown(run_data, comparison, found[0].name if found else None)
    print()
    print(report)
    if saved:
        (results_dir / "latest.md").write_text(report, encoding="utf-8")
        print(f"Saved {saved}")
    summary_file = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as handle:
            handle.write(report)

    problems = []
    if run_data["summary"]["score"] < args.min_score:
        problems.append(f"score below {args.min_score * 100:.0f}%")
    if run_data["summary"]["safety_failures"]:
        problems.append("a safety case failed")
    if comparison is not None and comparison.score_change < -args.max_drop:
        problems.append(f"score dropped more than {args.max_drop * 100:.0f} points")
    if problems:
        print("Eval failed: " + "; ".join(problems) + ".", file=sys.stderr)
        return 1
    return 0


def fill(_: argparse.Namespace) -> int:
    """Write the snapshot's figure values and source families into golden.json."""
    data = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    expected = asyncio.run(compute_expected(load_cases()))
    changed = 0
    for raw in data["cases"]:
        found = expected[raw["id"]]
        expect = raw.setdefault("expect", {})
        for figure, value in zip(expect.get("figures", []), found["values"], strict=True):
            value = round(value, 4)
            if figure.get("value") != value:
                figure["value"] = value
                changed += 1
        if expect.get("sources") != found["sources"]:
            expect["sources"] = found["sources"]
            changed += 1
    GOLDEN_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {changed} values in {GOLDEN_PATH}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals", description=__doc__.split("\n")[0])
    parser.add_argument("command", nargs="?", default="run", choices=["run", "fill"])
    parser.add_argument(
        "--model",
        choices=["offline", "configured"],
        default="offline",
        help="offline: scripted model, no API key; configured: the LLM in .env",
    )
    parser.add_argument("--cases", help="comma-separated case ids")
    parser.add_argument("--category", help="technical, fundamental, comparison, what-if, safety")
    parser.add_argument("--min-score", type=float, default=0.8)
    parser.add_argument("--max-drop", type=float, default=0.05)
    parser.add_argument("--case-timeout", type=float, default=300.0)
    parser.add_argument("--delay", type=float, default=0.0, help="seconds between cases")
    parser.add_argument("--results-dir", default=str(RESULTS_DIR))
    parser.add_argument("--no-save", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    # force: the MCP SDK sets up logging when the tool server is imported.
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, force=True)
    return fill(args) if args.command == "fill" else run(args)


if __name__ == "__main__":
    raise SystemExit(main())
