"""One async entry point for chat completions with tool calling, across providers.

Every provider is reached through its OpenAI-compatible API, so switching between
Ollama on Colab (via ngrok) and a hosted model is a settings change, not a code change.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import openai

from .providers import ProviderConfig

logger = logging.getLogger("stock_api.llm")

Message = dict[str, Any]
ClientFactory = Callable[[ProviderConfig], Any]

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class LLMError(RuntimeError):
    """The model call failed and no fallback could answer."""


class LLMUnavailableError(LLMError):
    """The endpoint could not be reached (down, timed out, overloaded or tunnel offline)."""


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""
    # Set when the model produced arguments that are not a JSON object.
    arguments_error: str | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ChatResult:
    content: str
    tool_calls: list[ToolCall]
    usage: Usage
    provider: str
    model: str
    latency_ms: int
    finish_reason: str | None = None
    used_fallback: bool = False

    def assistant_message(self) -> Message:
        """The reply as a message to append to the history before sending tool results."""
        message: Message = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.raw_arguments or "{}"},
                }
                for call in self.tool_calls
            ]
        return message


def default_client_factory(config: ProviderConfig, *, timeout: float, max_retries: int) -> Any:
    return openai.AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=timeout,
        max_retries=max_retries,
        default_headers=config.headers or None,
    )


def estimate_cost(config: ProviderConfig, prompt_tokens: int, completion_tokens: int) -> float:
    cost = (
        prompt_tokens * config.price_input_per_mtok
        + completion_tokens * config.price_output_per_mtok
    ) / 1_000_000
    return round(cost, 6)


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks that some local reasoning models put in the content."""
    return _THINK_BLOCK.sub("", text).strip()


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str, str | None]:
    if isinstance(raw, dict):
        return raw, json.dumps(raw), None
    text = raw or ""
    if not text.strip():
        return {}, "{}", None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, text, f"invalid JSON: {exc.msg}"
    if not isinstance(parsed, dict):
        return {}, text, "arguments must be a JSON object"
    return parsed, text, None


def _is_unavailable(exc: Exception) -> bool:
    """Errors worth retrying on the fallback provider. Bad requests and auth errors are not."""
    if isinstance(
        exc, openai.APIConnectionError | openai.InternalServerError | openai.RateLimitError
    ):
        return True
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in (502, 503, 504):
            return True
        # An ngrok URL whose tunnel is offline answers 404 with an ERR_NGROK_* code.
        return exc.status_code == 404 and "ERR_NGROK" in str(exc.body or exc.message)
    return False


def mcp_tool_to_openai(name: str, description: str | None, input_schema: dict[str, Any]) -> dict:
    """Convert an MCP tool definition into the OpenAI `tools` format."""
    schema = dict(input_schema or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return {
        "type": "function",
        "function": {"name": name, "description": description or "", "parameters": schema},
    }


class LLMGateway:
    def __init__(
        self,
        primary: ProviderConfig,
        fallback: ProviderConfig | None = None,
        *,
        timeout: float = 120.0,
        max_retries: int = 1,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self._factory: ClientFactory = client_factory or (
            lambda config: default_client_factory(config, timeout=timeout, max_retries=max_retries)
        )
        self._clients: dict[str, Any] = {}

    def _client(self, config: ProviderConfig) -> Any:
        key = f"{config.provider}|{config.base_url}"
        if key not in self._clients:
            self._clients[key] = self._factory(config)
        return self._clients[key]

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> ChatResult:
        configs = [self.primary] + ([self.fallback] if self.fallback else [])
        last_error: Exception | None = None
        for index, config in enumerate(configs):
            try:
                return await self._call(
                    config,
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    used_fallback=index > 0,
                )
            except openai.OpenAIError as exc:
                last_error = exc
                unavailable = _is_unavailable(exc)
                logger.warning(
                    "llm call failed provider=%s error=%s unavailable=%s",
                    config.label,
                    type(exc).__name__,
                    unavailable,
                )
                if not unavailable:
                    raise LLMError(f"{config.label}: {type(exc).__name__}: {exc}") from exc
        raise LLMUnavailableError(
            f"No LLM provider could be reached ({', '.join(c.label for c in configs)}): "
            f"{type(last_error).__name__}"
        ) from last_error

    async def _call(
        self,
        config: ProviderConfig,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float,
        max_tokens: int | None,
        used_fallback: bool,
    ) -> ChatResult:
        request: dict[str, Any] = {
            "model": config.model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if tools:
            request["tools"] = list(tools)
            if tool_choice is not None:
                request["tool_choice"] = tool_choice
        if max_tokens is not None:
            request["max_tokens"] = max_tokens

        started = time.perf_counter()
        response = await self._client(config).chat.completions.create(**request)
        latency_ms = int((time.perf_counter() - started) * 1000)

        if not response.choices:
            raise LLMError(f"{config.label}: response has no choices")
        choice = response.choices[0]
        message = choice.message

        calls: list[ToolCall] = []
        for index, raw_call in enumerate(message.tool_calls or []):
            function = getattr(raw_call, "function", None)
            if function is None:
                continue
            arguments, raw_text, error = _parse_arguments(function.arguments)
            calls.append(
                ToolCall(
                    id=raw_call.id or f"call_{index}",
                    name=function.name,
                    arguments=arguments,
                    raw_arguments=raw_text,
                    arguments_error=error,
                )
            )

        prompt_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(response.usage, "completion_tokens", 0) or 0
        usage = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=getattr(response.usage, "total_tokens", 0)
            or prompt_tokens + completion_tokens,
            cost_usd=estimate_cost(config, prompt_tokens, completion_tokens),
        )
        result = ChatResult(
            content=strip_thinking(message.content or ""),
            tool_calls=calls,
            usage=usage,
            provider=config.provider,
            model=response.model or config.model,
            latency_ms=latency_ms,
            finish_reason=choice.finish_reason,
            used_fallback=used_fallback,
        )
        logger.info(
            "llm call provider=%s model=%s prompt_tokens=%d completion_tokens=%d "
            "cost_usd=%.6f latency_ms=%d tool_calls=%d fallback=%s",
            result.provider,
            result.model,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.cost_usd,
            latency_ms,
            len(calls),
            used_fallback,
        )
        return result
