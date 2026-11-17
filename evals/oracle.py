"""An offline stand-in for the model: it makes each case's tool calls and states its figures.

It needs no API key, so CI can run the whole eval on every change to the agent, the prompt or
the tools. A perfect offline score means the harness, the tools on the frozen snapshot, the
grounding check and the disclaimer logic all agree with the golden answers; it says nothing
about a real model, which `--model configured` measures.
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai.types.chat import ChatCompletionChunk

from stock_api.llm import LLMGateway, ProviderConfig

from .golden import Case, Figure

ORACLE_LABEL = "offline-oracle"
_STANDALONE_NUMBER = re.compile(r"\s*\b\d+\b")


def _chunk(delta: dict[str, Any], finish: str | None = None) -> ChatCompletionChunk:
    return ChatCompletionChunk.model_validate(
        {
            "id": "oracle",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": ORACLE_LABEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


def format_value(value: float) -> str:
    """How a careful answer would write the figure (full precision, with a scale word)."""
    size = abs(value)
    if size >= 1e12:
        return f"{value / 1e12:.3f} trillion"
    if size >= 1e9:
        return f"{value / 1e9:.2f} billion"
    if size >= 1e6:
        return f"{value / 1e6:.2f} million"
    return f"{value:.2f}"


def oracle_answer(case: Case) -> str:
    def line(figure: Figure) -> str:
        # Numbers inside labels ("RSI 14", "year 5") are names, not figures to check.
        label = _STANDALONE_NUMBER.sub("", figure.label).strip(" ,")
        return f"- {label}: {format_value(figure.value or 0.0)}"

    lines = [line(f) for f in case.figures]
    if case.mentions:
        lines.append("Key terms: " + ", ".join(case.mentions) + ".")
    return "\n".join(lines) or "Here is the information the tools returned."


class _Stream:
    def __init__(self, chunks: list[ChatCompletionChunk]) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration from None


class OracleClient:
    """An OpenAI-style client that answers from the golden case matching the question."""

    def __init__(self, cases: list[Case]) -> None:
        self.cases = {case.question: case for case in cases}
        self.chat = self
        self.completions = self

    def _case(self, messages: list[dict[str, Any]]) -> Case:
        for message in messages:
            if message.get("role") == "user" and message.get("content") in self.cases:
                return self.cases[str(message["content"])]
        raise LookupError("the offline model got a question that is not in the golden set")

    async def create(self, **kwargs: Any) -> Any:
        messages: list[dict[str, Any]] = kwargs.get("messages", [])
        case = self._case(messages)
        last = messages[-1] if messages else {}
        asking = last.get("role") == "user" and last.get("content") == case.question
        calls = case.oracle_calls() if asking and kwargs.get("tools") else []
        if calls:
            chunks = [
                _chunk(
                    {
                        "tool_calls": [
                            {
                                "index": index,
                                "id": f"call_{index}",
                                "type": "function",
                                "function": {
                                    "name": call.tool,
                                    "arguments": json.dumps(call.args),
                                },
                            }
                        ]
                    }
                )
                for index, call in enumerate(calls)
            ]
            return _Stream([*chunks, _chunk({}, "tool_calls")])
        return _Stream([_chunk({"content": oracle_answer(case)}), _chunk({}, "stop")])


def oracle_gateway(cases: list[Case]) -> LLMGateway:
    client = OracleClient(cases)
    config = ProviderConfig(
        provider="ollama", model=ORACLE_LABEL, base_url="http://oracle.invalid/v1", api_key="-"
    )
    return LLMGateway(config, client_factory=lambda _config: client)
