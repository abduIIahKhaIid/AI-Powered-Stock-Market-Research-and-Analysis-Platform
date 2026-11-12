"""Which tools the model may see and call in a turn.

Approvals for sensitive actions (sandbox code, long jobs, paid APIs) come in SCRUM-26.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..llm import ToolCall
from .toolbox import ToolSpec


@dataclass(frozen=True)
class ToolPolicy:
    # None means every tool the MCP servers offer, minus the blocked ones.
    allowed_tools: frozenset[str] | None = None
    blocked_tools: frozenset[str] = field(default_factory=lambda: frozenset({"ping"}))
    max_tool_calls: int = 8

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
        if calls_made >= self.max_tool_calls:
            return (
                f"Tool budget of {self.max_tool_calls} calls for this question is used up. "
                "Answer with the data already gathered."
            )
        return None
