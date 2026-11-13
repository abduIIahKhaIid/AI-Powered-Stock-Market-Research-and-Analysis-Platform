"""Tool calls written as text by small models are run as real tool calls."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fakes import scripted_gateway, text_turn

from stock_api.agent import Agent, MemoryConversationStore, ToolOutcome, ToolSpec
from stock_api.agent.text_tools import tool_call_in_text

KNOWN = {"get_quote", "run_python_analysis"}
ARGS = {"symbols": ["AAPL", "MSFT"], "code": 'result = {"x": 1}'}


@pytest.mark.parametrize(
    "text",
    [
        json.dumps({"name": "run_python_analysis", "arguments": ARGS}),
        "```json\n" + json.dumps({"name": "run_python_analysis", "arguments": ARGS}) + "\n```",
        "<tool_call>"
        + json.dumps({"name": "run_python_analysis", "arguments": ARGS})
        + "</tool_call>",
        "I will run it now:\n" + json.dumps({"name": "run_python_analysis", "parameters": ARGS}),
        json.dumps({"function": {"name": "run_python_analysis", "arguments": json.dumps(ARGS)}}),
    ],
)
def test_written_tool_calls_are_recognised(text: str) -> None:
    call = tool_call_in_text(text, KNOWN)
    assert call is not None and call.name == "run_python_analysis" and call.arguments == ARGS
    assert json.loads(call.raw_arguments) == ARGS


@pytest.mark.parametrize(
    "text",
    [
        "Apple closed at 231.5 USD.",
        json.dumps({"name": "delete_everything", "arguments": {}}),
        '{"name": "get_quote", "arguments": "not json"}',
        'Example: {"name": "Apple", "ticker": "AAPL"}',
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert tool_call_in_text(text, KNOWN) is None


class Toolbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec("get_quote", "Quote")]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        return ToolOutcome(
            name, arguments, ok=True, payload={"data": {"price": 231.5}, "source": "Test"}
        )


async def test_the_agent_runs_a_tool_call_written_as_text() -> None:
    toolbox = Toolbox()
    written = json.dumps({"name": "get_quote", "arguments": {"symbol": "AAPL"}})
    gateway, _ = scripted_gateway(text_turn(written), text_turn("AAPL is at 231.5 USD."))

    @asynccontextmanager
    async def factory() -> AsyncIterator[Toolbox]:
        yield toolbox

    agent = Agent(gateway, factory, MemoryConversationStore())
    events = [event async for event in agent.run("AAPL price?")]
    assert toolbox.calls == [("get_quote", {"symbol": "AAPL"})]
    assert [e.type for e in events if e.type in ("tool_call", "tool_result")] == [
        "tool_call",
        "tool_result",
    ]
    assert events[-1].type == "done" and events[-1].data["answer"] == "AAPL is at 231.5 USD."
