"""The golden-answer set: loading cases and working out their expected figures.

golden.json holds each question with the figures a correct answer must contain. Every
figure also says where it comes from (a tool call on the frozen snapshot and a path into the
result), so `python -m evals fill` can recompute the values after the snapshot or a tool
changes, and a test checks that the stored values still match.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from financial_mcp.alpha_vantage import SOURCE_LABEL as AV_SOURCE
from financial_mcp.sec import SOURCE_LABEL as SEC_SOURCE

from .snapshot import PRICE_SOURCE

GOLDEN_PATH = Path(__file__).with_name("golden.json")
CATEGORIES = ("technical", "fundamental", "comparison", "what-if", "safety")
# Source families, most specific first: a source matches a family when it contains the label.
SOURCE_FAMILIES = (SEC_SOURCE, AV_SOURCE, PRICE_SOURCE)


@dataclass(frozen=True)
class FigureSource:
    tool: str
    args: dict[str, Any]
    path: str
    reduce: str | None = None


@dataclass(frozen=True)
class Figure:
    label: str
    value: float | None
    source: FigureSource
    tolerance_pct: float = 1.0


@dataclass(frozen=True)
class Call:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    question: str
    figures: tuple[Figure, ...] = ()
    tools: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    mentions: tuple[str, ...] = ()
    projection: bool = False
    forbid: tuple[str, ...] = ()
    forbid_calls: tuple[Call, ...] = ()
    # Extra calls the offline model makes (cases without figures, such as overviews).
    calls: tuple[Call, ...] = ()
    notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def oracle_calls(self) -> list[Call]:
        """The tool calls that gather this case's data, without repeats."""
        found: list[Call] = []
        for call in [*self.calls, *(Call(f.source.tool, f.source.args) for f in self.figures)]:
            if call not in found:
                found.append(call)
        return found


def _figure(raw: dict[str, Any]) -> Figure:
    src = raw["from"]
    return Figure(
        label=raw["label"],
        value=raw.get("value"),
        source=FigureSource(src["tool"], dict(src.get("args", {})), src["path"], src.get("reduce")),
        tolerance_pct=float(raw.get("tolerance_pct", 1.0)),
    )


def _call(raw: dict[str, Any]) -> Call:
    return Call(raw["tool"], dict(raw.get("args", {})))


def parse_case(raw: dict[str, Any]) -> Case:
    if raw.get("category") not in CATEGORIES:
        raise ValueError(f"{raw.get('id')}: unknown category {raw.get('category')!r}")
    expect = raw.get("expect", {})
    return Case(
        id=raw["id"],
        category=raw["category"],
        question=raw["question"],
        figures=tuple(_figure(f) for f in expect.get("figures", [])),
        tools=tuple(expect.get("tools", [])),
        sources=tuple(expect.get("sources", [])),
        mentions=tuple(expect.get("mentions", [])),
        projection=bool(expect.get("projection", False)),
        forbid=tuple(expect.get("forbid", [])),
        forbid_calls=tuple(_call(c) for c in expect.get("forbid_calls", [])),
        calls=tuple(_call(c) for c in raw.get("calls", [])),
        notes=raw.get("notes", ""),
        raw=raw,
    )


def load_cases(path: Path = GOLDEN_PATH) -> list[Case]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [parse_case(raw) for raw in data["cases"]]
    ids = [case.id for case in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate case ids: {', '.join(sorted(duplicates))}")
    return cases


# --- paths into tool results ----------------------------------------------------------------

_FILTER = re.compile(r"^(?P<key>[^\[]*)\[(?P<field>\w+)=(?P<value>[^\]]+)\]$")


def _step(node: Any, segment: str) -> list[Any]:
    if segment == "*":
        return list(node) if isinstance(node, list) else []
    match = _FILTER.match(segment)
    if match:
        items = node.get(match["key"]) if match["key"] else node
        if not isinstance(items, list):
            return []
        return [
            item
            for item in items
            if isinstance(item, dict) and str(item.get(match["field"])) == match["value"]
        ][:1]
    if isinstance(node, list):
        index = int(segment)
        return [node[index]] if -len(node) <= index < len(node) else []
    if isinstance(node, dict) and segment in node:
        return [node[segment]]
    return []


def resolve(payload: Any, path: str, reduce: str | None = None) -> float:
    """The number at `path` ("data.rows[metric=pe].cells.AAPL.value", "data.candles.*.close")."""
    nodes = [payload]
    for segment in path.split("."):
        nodes = [found for node in nodes for found in _step(node, segment)]
    numbers = [float(n) for n in nodes if isinstance(n, int | float) and not isinstance(n, bool)]
    if not numbers:
        raise KeyError(f"no number at {path}")
    if reduce == "max":
        return max(numbers)
    if reduce == "min":
        return min(numbers)
    if len(numbers) != 1:
        raise KeyError(f"{path} matches {len(numbers)} numbers; add reduce")
    return numbers[0]


def source_family(source: str | None) -> str | None:
    for family in SOURCE_FAMILIES:
        if source and family in source:
            return family
    return None
