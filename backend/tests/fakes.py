"""Fake LLM endpoint and market data shared by the agent tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2
import openai
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from financial_mcp.market_data import Candle
from financial_mcp.services import Services
from financial_mcp.symbols import NasdaqDirectory
from stock_api.llm import LLMGateway, ProviderConfig

REQUEST = httpx2.Request("POST", "http://llm.test/v1/chat/completions")
NASDAQ_SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "mcp_server"
    / "tests"
    / "fixtures"
    / "nasdaqlisted_sample.txt"
).read_text(encoding="utf-8")


class FakePrices:
    source = "Fake price source (tests)"

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        return [
            Candle("2026-11-09", 100.0, 103.0, 99.0, 102.0, 1_000_000),
            Candle("2026-11-10", 102.0, 106.0, 101.5, 105.0, 1_200_000),
            Candle("2026-11-11", 105.0, 107.5, 104.0, 107.1, 1_500_000),
        ]


def fake_services(cache_dir: Path) -> Services:
    directory = NasdaqDirectory(cache_dir=cache_dir, fetcher=lambda url: NASDAQ_SAMPLE)
    return Services(directory=directory, prices=FakePrices())


def chunk(
    content: str | None = None,
    tool_call: dict[str, Any] | None = None,
    finish: str | None = None,
) -> ChatCompletionChunk:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    return ChatCompletionChunk.model_validate(
        {
            "id": "c",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "fake-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


def text_turn(text: str) -> list[ChatCompletionChunk]:
    half = len(text) // 2
    return [chunk(text[:half]), chunk(text[half:]), chunk(finish="stop")]


def tool_turn(*calls: tuple[str, dict[str, Any]]) -> list[ChatCompletionChunk]:
    chunks = [
        chunk(
            tool_call={
                "index": index,
                "id": f"call_{index}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        )
        for index, (name, arguments) in enumerate(calls)
    ]
    return [*chunks, chunk(finish="tool_calls")]


def completion(text: str) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "x",
            "object": "chat.completion",
            "created": 0,
            "model": "fake-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }
    )


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


Outcome = list[ChatCompletionChunk] | ChatCompletion | Exception


class ScriptedLLM:
    """An OpenAI-style client that plays back one scripted outcome per request."""

    def __init__(self, outcomes: list[Outcome]) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[dict[str, Any]] = []
        self.chat = self
        self.completions = self

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        if not self.outcomes:
            raise AssertionError("the model was called more times than scripted")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, list):
            return _Stream(outcome)
        return outcome


def scripted_gateway(*outcomes: Outcome) -> tuple[LLMGateway, ScriptedLLM]:
    client = ScriptedLLM(list(outcomes))
    config = ProviderConfig(
        provider="ollama", model="fake-model", base_url="http://llm.test/v1", api_key="k"
    )
    return LLMGateway(config, client_factory=lambda c: client), client


def connection_error() -> Exception:
    return openai.APIConnectionError(request=REQUEST)
