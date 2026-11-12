"""Which tools the model may see and call in a turn.

Approvals for sensitive actions (sandbox code, long jobs, paid APIs) come in SCRUM-26.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from ..llm import ToolCall
from .toolbox import ToolSpec

_TICKER = re.compile(r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")
PERIODS = {"5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"}
INTERVALS = {"5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
MAX_SYMBOLS = 5
MAX_YEARS = 10
MAX_LIST = 10

# Kinds of action that always need the user's approval, recognised by tool name prefix.
APPROVAL_RULES: tuple[tuple[str, str], ...] = (
    ("run_python", "Runs model-written Python code in the sandbox."),
    ("execute_code", "Runs model-written code in the sandbox."),
    ("start_job", "Starts a background job that may take a while."),
    ("submit_job", "Starts a background job that may take a while."),
    ("export", "Exports data to a file."),
)


def _is_ticker(value: Any) -> bool:
    return isinstance(value, str) and bool(_TICKER.match(value))


def validate_arguments(arguments: dict[str, Any]) -> str | None:
    """Check common arguments before any tool runs; the reason when one is not allowed."""
    for key, value in arguments.items():
        if key == "symbol" and not _is_ticker(value):
            return f"'{value}' is not a valid ticker symbol."
        if key == "symbols":
            if not isinstance(value, list) or not value:
                return "symbols must be a list of ticker symbols."
            if len(value) > MAX_SYMBOLS:
                return f"Compare at most {MAX_SYMBOLS} symbols at a time."
            bad = [v for v in value if not _is_ticker(v)]
            if bad:
                return f"Not valid ticker symbols: {', '.join(map(str, bad))}."
        if key == "period" and value not in PERIODS:
            return f"Unsupported period '{value}'."
        if key == "interval" and value not in INTERVALS:
            return f"Unsupported interval '{value}'."
        if key == "years" and (not isinstance(value, int) or not 1 <= value <= MAX_YEARS):
            return f"years must be between 1 and {MAX_YEARS}."
        if key == "limit" and (not isinstance(value, int) or not 1 <= value <= 25):
            return "limit must be between 1 and 25."
        if key in ("indicators", "metrics") and isinstance(value, list) and len(value) > MAX_LIST:
            return f"Ask for at most {MAX_LIST} {key} at a time."
    return None


@dataclass(frozen=True)
class ToolPolicy:
    # None means every tool the MCP servers offer, minus the blocked ones.
    allowed_tools: frozenset[str] | None = None
    blocked_tools: frozenset[str] = field(default_factory=lambda: frozenset({"ping"}))
    max_tool_calls: int = 8
    # Tools that need the user's approval in addition to APPROVAL_RULES and tool metadata.
    approval_tools: frozenset[str] = field(default_factory=frozenset)

    def permits(self, name: str) -> bool:
        if name in self.blocked_tools:
            return False
        return self.allowed_tools is None or name in self.allowed_tools

    def visible(self, specs: Iterable[ToolSpec]) -> list[ToolSpec]:
        return [spec for spec in specs if self.permits(spec.name)]

    def refusal(self, call: ToolCall, calls_made: int, known: set[str]) -> str | None:
        """Why this call may not run, or None when it may."""
        if call.name not in known or not self.permits(call.name):
            return f"Tool '{call.name}' is not available. Use one of: {', '.join(sorted(known))}."
        if call.arguments_error:
            return f"Arguments for '{call.name}' were not valid JSON ({call.arguments_error})."
        invalid = validate_arguments(call.arguments)
        if invalid:
            return f"Arguments for '{call.name}' were rejected: {invalid}"
        if calls_made >= self.max_tool_calls:
            return (
                f"Tool budget of {self.max_tool_calls} calls for this question is used up. "
                "Answer with the data already gathered."
            )
        return None

    def approval_for(self, spec: ToolSpec) -> dict[str, Any] | None:
        """Why this tool needs the user's approval, or None when it does not."""
        if spec.approval:
            return {
                "reason": str(spec.approval.get("reason") or "This action needs your approval."),
                "estimate": spec.approval.get("estimate"),
            }
        for prefix, reason in APPROVAL_RULES:
            if spec.name.startswith(prefix):
                return {"reason": reason, "estimate": None}
        if spec.name in self.approval_tools:
            return {"reason": "This action is set to need your approval.", "estimate": None}
        return None
