"""Final answer packaging: sources, assumptions and the disclaimer (SCRUM-68)."""

from __future__ import annotations

import re
from typing import Any

from .context import DISCLAIMER
from .toolbox import ToolOutcome

PROJECTION_NOTE = (
    "Projections and what-if results are estimates built on the stated assumptions, "
    "not predictions of future prices."
)

_PROJECTION_WORDS = re.compile(
    r"\b(?:project(?:ion|ed|s)?|forecast\w*|predict\w*|what[- ]if|scenario\w*|target price|"
    r"intrinsic value|DCF|fair value|expected return|in \d+ years?|by 20\d\d|agar|"
    r"andaza|andaaza)\b",
    re.IGNORECASE,
)
_ASSUMPTION_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*|__)?\s*(?:Assumptions?|Mafroozat|Mafrozat)\b[^\n]*$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)")
_HEADING = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$)")
_LINK_KEYS = ("url", "link", "filing_url", "source_url")


def extract_assumptions(answer: str) -> list[str]:
    """List items under an 'Assumptions' heading in the answer."""
    items: list[str] = []
    lines = answer.splitlines()
    for index, line in enumerate(lines):
        if not _ASSUMPTION_HEADING.match(line):
            continue
        inline = line.split(":", 1)[1].strip(" *_") if ":" in line else ""
        if inline:
            items.append(inline)
        for following in lines[index + 1 :]:
            item = _LIST_ITEM.match(following)
            if item:
                items.append(item.group(1).strip())
            elif not following.strip():
                if items:
                    break
            elif _HEADING.match(following):
                break
            else:
                break
    return list(dict.fromkeys(items))


def tool_assumptions(outcomes: list[ToolOutcome]) -> list[str]:
    found: list[str] = []
    for outcome in outcomes:
        payload = outcome.payload
        data = payload.get("data") if isinstance(payload, dict) else None
        for holder in (payload, data):
            if isinstance(holder, dict) and isinstance(holder.get("assumptions"), list):
                found += [str(item) for item in holder["assumptions"] if str(item).strip()]
    return found


def source_link(payload: Any) -> str | None:
    for holder in (payload, payload.get("data") if isinstance(payload, dict) else None):
        if isinstance(holder, dict):
            for key in _LINK_KEYS:
                value = holder.get(key)
                if isinstance(value, str) and value.startswith(("https://", "http://")):
                    return value
    return None


def is_projection(question: str, answer: str, assumptions: list[str]) -> bool:
    return bool(assumptions) or bool(_PROJECTION_WORDS.search(f"{question}\n{answer}"))


def disclaimer_for(question: str, answer: str, assumptions: list[str]) -> str:
    if is_projection(question, answer, assumptions):
        return f"{DISCLAIMER} {PROJECTION_NOTE}"
    return DISCLAIMER
