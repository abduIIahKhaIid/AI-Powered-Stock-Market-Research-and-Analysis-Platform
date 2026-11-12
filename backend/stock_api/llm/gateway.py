"""One async entry point for chat completions with tool calling, across providers.

Every provider is reached through its OpenAI-compatible API, so switching between
Ollama on Colab (via ngrok) and a hosted model is a settings change, not a code change.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Sequence
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


def _hint(config: ProviderConfig, exc: Exception) -> str:
    """A next step for common setup mistakes, appended to the error message."""
    status = getattr(exc, "status_code", None)
    if config.provider == "ollama" and status == 403:
        return (
            ". Ollama rejected the request's Host header: start it with "
            "OLLAMA_HOST=0.0.0.0:11434, or run ngrok with --host-header=localhost:11434"
        )
    if config.provider == "ollama" and status == 404 and "not found" in str(exc).lower():
        return f". Pull the model first: ollama pull {config.model}"
    if status == 401:
        return ". Check the API key for this provider"
    return ""


def mcp_tool_to_openai(name: str, description: str | None, input_schema: dict[str, Any]) -> dict:
    """Convert an MCP tool definition into the OpenAI `tools` format."""
    schema = dict(input_schema or {})
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return {
        "type": "function",
        "function": {"name": name, "description": description or "", "parameters": schema},
    }


@dataclass(frozen=True)
class TextDelta:
    """A piece of the answer text, streamed as it is generated."""

    text: str


StreamEvent = TextDelta | ChatResult


class _ThinkFilter:
    """Drops <think>...</think> blocks from streamed text, even when tags span chunks."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self._pending = ""
        self._inside = False
        self._emitted_any = False

    def _emit(self, text: str) -> str:
        if not self._emitted_any:
            text = text.lstrip()
            if text:
                self._emitted_any = True
        return text

    def feed(self, text: str) -> str:
        self._pending += text
        out: list[str] = []
        while True:
            if self._inside:
                end = self._pending.find(self.CLOSE)
                if end < 0:
                    # Keep only what could be the start of the closing tag.
                    self._pending = self._pending[-(len(self.CLOSE) - 1) :]
                    break
                self._pending = self._pending[end + len(self.CLOSE) :]
                self._inside = False
                continue
            start = self._pending.find(self.OPEN)
            if start >= 0:
                out.append(self._pending[:start])
                self._pending = self._pending[start + len(self.OPEN) :]
                self._inside = True
                continue
            keep = 0
            for size in range(len(self.OPEN) - 1, 0, -1):
                if self._pending.endswith(self.OPEN[:size]):
                    keep = size
                    break
            out.append(self._pending[: len(self._pending) - keep])
            self._pending = self._pending[len(self._pending) - keep :]
            break
        return self._emit("".join(out))

    def flush(self) -> str:
        rest = "" if self._inside else self._pending
        self._pending = ""
        return self._emit(rest)


class LLMGateway:
    def __init__(
        self,
        primary: ProviderConfig,
        fallback: ProviderConfig | None = None,
        *,
        timeout: float = 120.0,
        max_retries: int = 1,
        primary_cooldown_seconds: float = 120.0,
        client_factory: ClientFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_cooldown_seconds = primary_cooldown_seconds
        self._factory: ClientFactory = client_factory or (
            lambda config: default_client_factory(config, timeout=timeout, max_retries=max_retries)
        )
        self._clients: dict[str, Any] = {}
        self._clock = clock
        self._primary_down_until = 0.0

    def _client(self, config: ProviderConfig) -> Any:
        key = f"{config.provider}|{config.base_url}"
        if key not in self._clients:
            self._clients[key] = self._factory(config)
        return self._clients[key]

    @property
    def primary_cooling_down(self) -> bool:
        return self.fallback is not None and self._clock() < self._primary_down_until

    def _order(self) -> list[tuple[ProviderConfig, bool]]:
        """Providers to try, each with a flag saying whether it is the fallback."""
        if self.fallback is None:
            return [(self.primary, False)]
        if self.primary_cooling_down:
            # The primary failed recently: go straight to the fallback, primary last.
            return [(self.fallback, True), (self.primary, False)]
        return [(self.primary, False), (self.fallback, True)]

    def _on_failure(self, config: ProviderConfig, exc: Exception) -> None:
        """Log the failure; raise LLMError unless the next provider should be tried."""
        unavailable = _is_unavailable(exc)
        logger.warning(
            "llm call failed provider=%s error=%s unavailable=%s",
            config.label,
            type(exc).__name__,
            unavailable,
        )
        if not unavailable:
            raise LLMError(
                f"{config.label}: {type(exc).__name__}: {exc}{_hint(config, exc)}"
            ) from exc
        if config is self.primary and self.fallback is not None:
            self._primary_down_until = self._clock() + self.primary_cooldown_seconds

    def _on_success(self, config: ProviderConfig) -> None:
        if config is self.primary:
            self._primary_down_until = 0.0

    def _unavailable(self, last_error: Exception | None) -> LLMUnavailableError:
        configs = [self.primary] + ([self.fallback] if self.fallback else [])
        labels = ", ".join(config.label for config in configs)
        return LLMUnavailableError(
            f"No LLM provider could be reached ({labels}): {type(last_error).__name__}"
        )

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> ChatResult:
        last_error: Exception | None = None
        for config, is_fallback in self._order():
            try:
                result = await self._call(
                    config,
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    used_fallback=is_fallback,
                )
            except openai.OpenAIError as exc:
                last_error = exc
                self._on_failure(config, exc)
                continue
            self._on_success(config)
            return result
        raise self._unavailable(last_error) from last_error

    async def stream_chat(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Yield TextDelta events as the answer arrives, then one final ChatResult.

        Falls back to the next provider only if nothing has been streamed yet.
        """
        last_error: Exception | None = None
        for config, is_fallback in self._order():
            streamed = False
            try:
                async for event in self._stream(
                    config,
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    used_fallback=is_fallback,
                ):
                    if isinstance(event, TextDelta):
                        streamed = True
                    yield event
            except openai.OpenAIError as exc:
                last_error = exc
                if streamed:
                    raise LLMError(
                        f"{config.label}: stream interrupted: {type(exc).__name__}"
                    ) from exc
                self._on_failure(config, exc)
                continue
            self._on_success(config)
            return
        raise self._unavailable(last_error) from last_error

    @staticmethod
    def _request(
        config: ProviderConfig,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
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
        return request

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
        request = self._request(config, messages, tools, tool_choice, temperature, max_tokens)
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
            calls.append(_tool_call(raw_call.id, index, function.name, function.arguments))

        return self._finish(
            config,
            content=strip_thinking(message.content or ""),
            calls=calls,
            usage=response.usage,
            model=response.model,
            finish_reason=choice.finish_reason,
            latency_ms=latency_ms,
            used_fallback=used_fallback,
        )

    async def _stream(
        self,
        config: ProviderConfig,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None,
        tool_choice: str | dict[str, Any] | None,
        temperature: float,
        max_tokens: int | None,
        used_fallback: bool,
    ) -> AsyncIterator[StreamEvent]:
        request = self._request(config, messages, tools, tool_choice, temperature, max_tokens)
        request["stream"] = True
        request["stream_options"] = {"include_usage": True}
        started = time.perf_counter()
        stream = await self._client(config).chat.completions.create(**request)

        think = _ThinkFilter()
        raw_text: list[str] = []
        partial_calls: dict[int, dict[str, Any]] = {}
        usage: Any = None
        model: str | None = None
        finish_reason: str | None = None

        async for chunk in stream:
            model = getattr(chunk, "model", None) or model
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            for choice in chunk.choices or []:
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta
                if delta is None:
                    continue
                if delta.content:
                    raw_text.append(delta.content)
                    visible = think.feed(delta.content)
                    if visible:
                        yield TextDelta(visible)
                for call_delta in delta.tool_calls or []:
                    slot = partial_calls.setdefault(
                        call_delta.index, {"id": None, "name": "", "arguments": ""}
                    )
                    if call_delta.id:
                        slot["id"] = call_delta.id
                    function = call_delta.function
                    if function is not None:
                        if function.name:
                            slot["name"] = function.name
                        if function.arguments:
                            slot["arguments"] += function.arguments

        tail = think.flush()
        if tail:
            yield TextDelta(tail)
        latency_ms = int((time.perf_counter() - started) * 1000)
        calls = [
            _tool_call(slot["id"], index, slot["name"], slot["arguments"])
            for index, slot in sorted(partial_calls.items())
            if slot["name"]
        ]
        yield self._finish(
            config,
            content=strip_thinking("".join(raw_text)),
            calls=calls,
            usage=usage,
            model=model,
            finish_reason=finish_reason,
            latency_ms=latency_ms,
            used_fallback=used_fallback,
        )

    def _finish(
        self,
        config: ProviderConfig,
        *,
        content: str,
        calls: list[ToolCall],
        usage: Any,
        model: str | None,
        finish_reason: str | None,
        latency_ms: int,
        used_fallback: bool,
    ) -> ChatResult:
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        totals = Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=getattr(usage, "total_tokens", 0) or prompt_tokens + completion_tokens,
            cost_usd=estimate_cost(config, prompt_tokens, completion_tokens),
        )
        result = ChatResult(
            content=content,
            tool_calls=calls,
            usage=totals,
            provider=config.provider,
            model=model or config.model,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            used_fallback=used_fallback,
        )
        logger.info(
            "llm call provider=%s model=%s prompt_tokens=%d completion_tokens=%d "
            "cost_usd=%.6f latency_ms=%d tool_calls=%d fallback=%s",
            result.provider,
            result.model,
            totals.prompt_tokens,
            totals.completion_tokens,
            totals.cost_usd,
            latency_ms,
            len(calls),
            used_fallback,
        )
        return result


def _tool_call(call_id: str | None, index: int, name: str, raw_arguments: Any) -> ToolCall:
    arguments, raw_text, error = _parse_arguments(raw_arguments)
    return ToolCall(
        id=call_id or f"call_{index}",
        name=name,
        arguments=arguments,
        raw_arguments=raw_text,
        arguments_error=error,
    )
