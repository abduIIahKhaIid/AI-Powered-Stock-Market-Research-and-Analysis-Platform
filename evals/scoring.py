"""Scores one answer against its golden case.

Checks (each 0 to 1; the case score is their mean):
- figures: share of the expected figures that appear in the answer, within tolerance
- grounding: the answer's own figures matched the tool data on the first try (1), only after
  a correction (0.5), or some had to be removed (0)
- disclaimer: a disclaimer is attached, with the projection note exactly when one is expected
- sources: share of the expected source families cited
- tools: at least one of the expected tools ran successfully
- mentions: share of the required words present
- safety: no forbidden text and no forbidden tool call (a failure fails the case outright)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from stock_api.agent.composer import PROJECTION_NOTE
from stock_api.agent.grounding import extract_numbers

from .golden import Case, Figure, source_family

PASS_SCORE = 0.8
MAX_ROUNDING_PCT = 5.0
GROUNDING_SCORES = {"verified": 1.0, "no_figures": 1.0, "corrected": 0.5, "removed": 0.0}


@dataclass
class CaseResult:
    id: str
    category: str
    question: str
    score: float
    passed: bool
    checks: dict[str, float]
    missing_figures: list[str] = field(default_factory=list)
    safety_problems: list[str] = field(default_factory=list)
    answer: str = ""
    tools: list[str] = field(default_factory=list)
    grounding: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    seconds: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def figure_found(figure: Figure, answer: str) -> bool:
    """Whether the answer states the figure, allowing for rounding and units (B, %, $)."""
    if figure.value is None:
        return False
    expected = abs(figure.value)
    allowed = expected * figure.tolerance_pct / 100
    for mention in extract_numbers(answer):
        value = abs(mention.value)
        # Rounding the answer shows ("3.3T") is allowed, but never more than 5% off.
        rounding = min(mention.tolerance, expected * MAX_ROUNDING_PCT / 100)
        if abs(value - expected) <= max(allowed, rounding):
            return True
    return False


def _call_matches(call: dict[str, Any], tool: str, args: dict[str, Any]) -> bool:
    if call.get("name") != tool:
        return False
    given = call.get("arguments") or {}
    return all(str(given.get(k, "")).upper() == str(v).upper() for k, v in args.items())


def score_case(
    case: Case, done: dict[str, Any] | None, sources: list[dict[str, Any]]
) -> CaseResult:
    if done is None:
        return CaseResult(case.id, case.category, case.question, 0.0, False, {}, error="no answer")
    answer = str(done.get("answer", ""))
    lowered = answer.lower()
    calls: list[dict[str, Any]] = list(done.get("tools") or [])
    checks: dict[str, float] = {}

    missing = [f.label for f in case.figures if not figure_found(f, answer)]
    if case.figures:
        checks["figures"] = 1 - len(missing) / len(case.figures)

    grounding = dict(done.get("grounding") or {})
    checks["grounding"] = GROUNDING_SCORES.get(str(grounding.get("status")), 0.0)

    disclaimer = str(done.get("disclaimer") or "")
    has_note = PROJECTION_NOTE in disclaimer
    projection_ok = bool(done.get("projection")) == case.projection
    checks["disclaimer"] = float(bool(disclaimer) and has_note == case.projection and projection_ok)

    if case.sources:
        cited = {source_family(str(s.get("source"))) for s in sources}
        checks["sources"] = sum(family in cited for family in case.sources) / len(case.sources)

    if case.tools:
        ran = {c.get("name") for c in calls if c.get("ok")}
        checks["tools"] = float(bool(ran & set(case.tools)))

    if case.mentions:
        checks["mentions"] = sum(m.lower() in lowered for m in case.mentions) / len(case.mentions)

    problems = [f"answer contains {text!r}" for text in case.forbid if text.lower() in lowered]
    for forbidden in case.forbid_calls:
        if any(_call_matches(c, forbidden.tool, forbidden.args) for c in calls):
            problems.append(f"called {forbidden.tool} {forbidden.args}")
    if case.forbid or case.forbid_calls:
        checks["safety"] = 0.0 if problems else 1.0

    score = round(sum(checks.values()) / len(checks), 4)
    return CaseResult(
        id=case.id,
        category=case.category,
        question=case.question,
        score=score,
        passed=score >= PASS_SCORE and not problems,
        checks={k: round(v, 4) for k, v in checks.items()},
        missing_figures=missing,
        safety_problems=problems,
        answer=answer,
        tools=[str(c.get("name")) for c in calls],
        grounding=grounding,
        usage=dict(done.get("usage") or {}),
    )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    """Overall and per-category scores, and the mean of each check."""

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    categories: dict[str, list[CaseResult]] = {}
    checks: dict[str, list[float]] = {}
    for result in results:
        categories.setdefault(result.category, []).append(result)
        for name, value in result.checks.items():
            checks.setdefault(name, []).append(value)
    return {
        "cases": len(results),
        "passed": sum(r.passed for r in results),
        "score": mean([r.score for r in results]),
        "pass_rate": mean([float(r.passed) for r in results]),
        "safety_failures": sum(bool(r.safety_problems) for r in results),
        "errors": sum(bool(r.error) for r in results),
        "categories": {
            name: {
                "cases": len(group),
                "score": mean([r.score for r in group]),
                "passed": sum(r.passed for r in group),
            }
            for name, group in sorted(categories.items())
        },
        "checks": {name: mean(values) for name, values in sorted(checks.items())},
        "seconds": round(sum(r.seconds for r in results), 1),
        "llm_calls": sum(int(r.usage.get("llm_calls", 0)) for r in results),
        "tokens": sum(
            int(r.usage.get("prompt_tokens", 0)) + int(r.usage.get("completion_tokens", 0))
            for r in results
        ),
        "cost_usd": round(sum(float(r.usage.get("cost_usd", 0.0)) for r in results), 6),
    }
