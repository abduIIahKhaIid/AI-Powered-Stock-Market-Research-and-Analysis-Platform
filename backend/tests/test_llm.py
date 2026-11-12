from typing import Any

import httpx2
import openai
import pytest
from openai.types.chat import ChatCompletion

from stock_api.config import Settings
from stock_api.llm import (
    LLMConfigError,
    LLMError,
    LLMGateway,
    LLMUnavailableError,
    ProviderConfig,
    build_gateway,
    mcp_tool_to_openai,
    resolve_provider,
)
from stock_api.llm.gateway import strip_thinking

# openai 3.x is built on httpx2, so its error types expect httpx2 objects.
REQUEST = httpx2.Request("POST", "http://llm.test/v1/chat/completions")


def completion(
    content: str | None = "hello",
    tool_calls: list[dict[str, Any]] | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    model: str = "qwen3:8b",
) -> ChatCompletion:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
    )


class FakeCompletions:
    def __init__(self, outcome: ChatCompletion | Exception) -> None:
        self.outcome = outcome
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> ChatCompletion:
        self.requests.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeClient:
    def __init__(self, outcome: ChatCompletion | Exception) -> None:
        self.completions = FakeCompletions(outcome)
        self.chat = self


def config(provider: str = "ollama", model: str = "qwen3:8b", **kwargs: Any) -> ProviderConfig:
    return ProviderConfig(
        provider=provider, model=model, base_url="http://llm.test/v1", api_key="k", **kwargs
    )


def gateway_with(
    primary_outcome: ChatCompletion | Exception,
    fallback_outcome: ChatCompletion | Exception | None = None,
    **primary_kwargs: Any,
) -> tuple[LLMGateway, dict[str, FakeClient]]:
    clients = {"ollama": FakeClient(primary_outcome)}
    fallback = None
    if fallback_outcome is not None:
        clients["groq"] = FakeClient(fallback_outcome)
        fallback = config("groq", "llama-3.3-70b-versatile")
    gateway = LLMGateway(
        config(**primary_kwargs), fallback, client_factory=lambda c: clients[c.provider]
    )
    return gateway, clients


# --- provider resolution -------------------------------------------------------------


def test_ollama_ngrok_url_gets_v1_path_and_skip_warning_header() -> None:
    cfg = resolve_provider("ollama", "qwen3:8b", api_base="https://abc123.ngrok-free.app/")
    assert cfg.base_url == "https://abc123.ngrok-free.app/v1"
    assert cfg.headers["ngrok-skip-browser-warning"] == "true"
    assert cfg.api_key == "ollama"


def test_ollama_base_already_ending_in_v1_is_not_doubled() -> None:
    cfg = resolve_provider("Ollama", "qwen3:8b", api_base="http://host.docker.internal:11434/v1")
    assert cfg.base_url == "http://host.docker.internal:11434/v1"
    assert "ngrok-skip-browser-warning" not in cfg.headers


def test_ollama_default_base_url() -> None:
    assert resolve_provider("ollama", "qwen3:8b").base_url == "http://localhost:11434/v1"


def test_hosted_provider_uses_preset_url() -> None:
    cfg = resolve_provider("groq", "llama-3.3-70b-versatile", api_key="gsk_x")
    assert cfg.base_url == "https://api.groq.com/openai/v1"
    assert cfg.headers == {}


@pytest.mark.parametrize(
    ("provider", "model", "kwargs", "message"),
    [
        ("mystery", "m", {}, "Unknown LLM provider"),
        ("ollama", "", {}, "LLM_MODEL"),
        ("groq", "llama", {}, "LLM_API_KEY"),
        ("custom", "m", {}, "LLM_API_BASE"),
    ],
)
def test_invalid_settings_raise_config_error(
    provider: str, model: str, kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(LLMConfigError, match=message):
        resolve_provider(provider, model, **kwargs)


def test_build_gateway_with_fallback() -> None:
    settings = Settings(
        llm_provider="ollama",
        llm_model="qwen3:8b",
        llm_api_base="https://abc.ngrok-free.app",
        llm_fallback_provider="gemini",
        llm_fallback_model="gemini-2.5-flash",
        llm_fallback_api_key="AIza-test",
    )
    gateway = build_gateway(settings)
    assert gateway.primary.label == "ollama/qwen3:8b"
    assert gateway.fallback is not None
    assert gateway.fallback.base_url.startswith("https://generativelanguage.googleapis.com")
    assert "ngrok-skip-browser-warning" not in gateway.fallback.headers


def test_build_gateway_requires_model() -> None:
    with pytest.raises(LLMConfigError):
        build_gateway(Settings(llm_provider="ollama", llm_model=""))


# --- chat ----------------------------------------------------------------------------


async def test_plain_reply_usage_and_cost() -> None:
    gateway, clients = gateway_with(
        completion("AAPL is up today.", prompt_tokens=1_000, completion_tokens=500),
        price_input_per_mtok=2.0,
        price_output_per_mtok=8.0,
    )
    result = await gateway.chat([{"role": "user", "content": "hi"}], temperature=0)

    assert result.content == "AAPL is up today."
    assert result.tool_calls == []
    assert result.usage.total_tokens == 1_500
    assert result.usage.cost_usd == pytest.approx(0.006)
    assert result.provider == "ollama"
    assert result.used_fallback is False
    sent = clients["ollama"].completions.requests[0]
    assert sent["model"] == "qwen3:8b"
    assert sent["temperature"] == 0
    assert "tools" not in sent


async def test_tool_calls_are_parsed_and_tools_forwarded() -> None:
    tool = mcp_tool_to_openai("get_quote", "Quote", {"properties": {"symbol": {"type": "string"}}})
    gateway, clients = gateway_with(
        completion(
            None,
            tool_calls=[
                {
                    "id": "call_9",
                    "type": "function",
                    "function": {"name": "get_quote", "arguments": '{"symbol": "AAPL"}'},
                }
            ],
        )
    )
    result = await gateway.chat(
        [{"role": "user", "content": "AAPL price?"}], tools=[tool], tool_choice="auto"
    )

    assert result.content == ""
    assert result.finish_reason == "tool_calls"
    call = result.tool_calls[0]
    assert (call.id, call.name, call.arguments) == ("call_9", "get_quote", {"symbol": "AAPL"})
    assert call.arguments_error is None
    sent = clients["ollama"].completions.requests[0]
    assert sent["tools"][0]["function"]["parameters"]["type"] == "object"
    assert sent["tool_choice"] == "auto"
    history_entry = result.assistant_message()
    assert history_entry["tool_calls"][0]["function"]["arguments"] == '{"symbol": "AAPL"}'


async def test_malformed_tool_arguments_are_reported_not_raised() -> None:
    gateway, _ = gateway_with(
        completion(
            None,
            tool_calls=[
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_quote", "arguments": "{symbol: AAPL"},
                }
            ],
        )
    )
    result = await gateway.chat([{"role": "user", "content": "x"}])
    assert result.tool_calls[0].arguments == {}
    assert result.tool_calls[0].arguments_error is not None


async def test_thinking_block_is_stripped() -> None:
    gateway, _ = gateway_with(completion("<think>let me reason</think>\nFinal answer."))
    result = await gateway.chat([{"role": "user", "content": "x"}])
    assert result.content == "Final answer."


def test_strip_thinking_leaves_normal_text() -> None:
    assert strip_thinking("  plain text ") == "plain text"


# --- fallback ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=REQUEST),
        openai.APITimeoutError(request=REQUEST),
        openai.InternalServerError(
            "bad gateway", response=httpx2.Response(502, request=REQUEST), body=None
        ),
        openai.NotFoundError(
            "tunnel offline",
            response=httpx2.Response(404, request=REQUEST),
            body="The endpoint abc.ngrok-free.app is offline. ERR_NGROK_3200",
        ),
    ],
)
async def test_unreachable_primary_falls_back(error: Exception) -> None:
    gateway, clients = gateway_with(error, completion("from groq", model="llama-3.3"))
    result = await gateway.chat([{"role": "user", "content": "x"}])
    assert result.content == "from groq"
    assert result.provider == "groq"
    assert result.used_fallback is True
    assert len(clients["ollama"].completions.requests) == 1


async def test_bad_request_does_not_fall_back() -> None:
    error = openai.BadRequestError(
        "model does not support tools", response=httpx2.Response(400, request=REQUEST), body=None
    )
    gateway, clients = gateway_with(error, completion("unused"))
    with pytest.raises(LLMError, match="BadRequestError"):
        await gateway.chat([{"role": "user", "content": "x"}])
    assert clients["groq"].completions.requests == []


async def test_both_unreachable_raises_unavailable() -> None:
    gateway, _ = gateway_with(
        openai.APIConnectionError(request=REQUEST), openai.APIConnectionError(request=REQUEST)
    )
    with pytest.raises(LLMUnavailableError, match="ollama/qwen3:8b, groq/"):
        await gateway.chat([{"role": "user", "content": "x"}])


async def test_unreachable_without_fallback_raises_unavailable() -> None:
    gateway, _ = gateway_with(openai.APIConnectionError(request=REQUEST))
    with pytest.raises(LLMUnavailableError):
        await gateway.chat([{"role": "user", "content": "x"}])


async def test_ollama_403_explains_host_header_fix() -> None:
    error = openai.PermissionDeniedError(
        "Error code: 403", response=httpx2.Response(403, request=REQUEST), body=None
    )
    gateway, clients = gateway_with(error, completion("unused"))
    with pytest.raises(LLMError, match="OLLAMA_HOST=0.0.0.0"):
        await gateway.chat([{"role": "user", "content": "x"}])
    assert clients["groq"].completions.requests == []


async def test_missing_ollama_model_suggests_pull() -> None:
    error = openai.NotFoundError(
        "model 'qwen3:8b' not found", response=httpx2.Response(404, request=REQUEST), body=None
    )
    gateway, _ = gateway_with(error)
    with pytest.raises(LLMError, match="ollama pull qwen3:8b"):
        await gateway.chat([{"role": "user", "content": "x"}])


# --- streaming ------------------------------------------------------------------------

from openai.types.chat import ChatCompletionChunk  # noqa: E402

from stock_api.llm import TextDelta  # noqa: E402
from stock_api.llm.gateway import _ThinkFilter  # noqa: E402


def chunk(
    content: str | None = None,
    tool_call: dict[str, Any] | None = None,
    finish: str | None = None,
    usage: dict[str, int] | None = None,
) -> ChatCompletionChunk:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if tool_call is not None:
        delta["tool_calls"] = [tool_call]
    data: dict[str, Any] = {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "qwen3:4b",
        "choices": [] if usage else [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage:
        data["usage"] = usage
    return ChatCompletionChunk.model_validate(data)


class FakeStream:
    def __init__(self, chunks: list[ChatCompletionChunk], fail_after: int | None = None) -> None:
        self.chunks = chunks
        self.fail_after = fail_after

    def __aiter__(self) -> "FakeStream":
        self.index = 0
        return self

    async def __anext__(self) -> ChatCompletionChunk:
        if self.fail_after is not None and self.index == self.fail_after:
            raise openai.APIConnectionError(request=REQUEST)
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        self.index += 1
        return self.chunks[self.index - 1]


async def collect(gateway: LLMGateway, **kwargs: Any) -> tuple[str, Any]:
    text, final = [], None
    async for event in gateway.stream_chat([{"role": "user", "content": "x"}], **kwargs):
        if isinstance(event, TextDelta):
            text.append(event.text)
        else:
            final = event
    return "".join(text), final


async def test_stream_yields_text_and_final_result_without_thinking() -> None:
    stream = FakeStream(
        [
            chunk("<thi"),
            chunk("nk>private reasoning</th"),
            chunk("ink>\n\nAAPL closed "),
            chunk("at 107.1 USD."),
            chunk(finish="stop"),
            chunk(usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}),
        ]
    )
    gateway, clients = gateway_with(stream)  # type: ignore[arg-type]
    text, final = await collect(gateway)
    assert text == "AAPL closed at 107.1 USD."
    assert final.content == "AAPL closed at 107.1 USD."
    assert final.usage.total_tokens == 20
    assert final.finish_reason == "stop"
    sent = clients["ollama"].completions.requests[0]
    assert sent["stream"] is True


async def test_stream_accumulates_tool_call_deltas() -> None:
    stream = FakeStream(
        [
            chunk(
                tool_call={
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_quote", "arguments": '{"sym'},
                }
            ),
            chunk(tool_call={"index": 0, "function": {"arguments": 'bol": "NVDA"}'}}),
            chunk(finish="tool_calls"),
        ]
    )
    gateway, _ = gateway_with(stream)  # type: ignore[arg-type]
    text, final = await collect(gateway, tools=[QUOTE])
    assert text == ""
    assert [(c.id, c.name, c.arguments) for c in final.tool_calls] == [
        ("call_1", "get_quote", {"symbol": "NVDA"})
    ]


async def test_stream_falls_back_when_primary_fails_before_any_text() -> None:
    gateway, _ = gateway_with(
        openai.APIConnectionError(request=REQUEST),
        FakeStream([chunk("from groq"), chunk(finish="stop")]),  # type: ignore[arg-type]
    )
    text, final = await collect(gateway)
    assert text == "from groq"
    assert final.used_fallback is True


async def test_stream_interrupted_after_text_raises() -> None:
    gateway, _ = gateway_with(
        FakeStream([chunk("partial"), chunk(" answer")], fail_after=1),  # type: ignore[arg-type]
        FakeStream([chunk("unused")]),  # type: ignore[arg-type]
    )
    with pytest.raises(LLMError, match="stream interrupted"):
        await collect(gateway)


@pytest.mark.parametrize(
    ("pieces", "expected"),
    [
        (["plain ", "text"], "plain text"),
        (["<think>a</think>b"], "b"),
        (["x <", "b> y"], "x <b> y"),
        (["<think>never closed"], ""),
        (["a<thi", "s is not a tag"], "a<this is not a tag"),
    ],
)
def test_think_filter(pieces: list[str], expected: str) -> None:
    think = _ThinkFilter()
    out = "".join(think.feed(piece) for piece in pieces) + think.flush()
    assert out == expected


# --- primary cooldown -----------------------------------------------------------------

QUOTE = mcp_tool_to_openai("get_quote", "Quote", {"properties": {"symbol": {"type": "string"}}})


class ScriptedCompletions:
    """Returns or raises the next scripted outcome on each call."""

    def __init__(self, outcomes: list[ChatCompletion | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def create(self, **kwargs: Any) -> ChatCompletion:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ScriptedClient:
    def __init__(self, outcomes: list[ChatCompletion | Exception]) -> None:
        self.completions = ScriptedCompletions(outcomes)
        self.chat = self


async def test_failed_primary_is_skipped_during_cooldown_then_retried() -> None:
    now = [1000.0]
    primary = ScriptedClient(
        [openai.APIConnectionError(request=REQUEST), completion("primary back")]
    )
    fallback = ScriptedClient([completion("from groq")])
    clients: dict[str, Any] = {"ollama": primary, "groq": fallback}
    gateway = LLMGateway(
        config(),
        config("groq", "llama"),
        primary_cooldown_seconds=120,
        client_factory=lambda c: clients[c.provider],
        clock=lambda: now[0],
    )
    first = await gateway.chat([{"role": "user", "content": "x"}])
    assert first.provider == "groq"
    assert gateway.primary_cooling_down

    now[0] += 60
    second = await gateway.chat([{"role": "user", "content": "x"}])
    assert second.provider == "groq"
    assert primary.completions.calls == 1  # primary not tried during cooldown

    now[0] += 61
    third = await gateway.chat([{"role": "user", "content": "x"}])
    assert third.content == "primary back"
    assert third.used_fallback is False
    assert not gateway.primary_cooling_down
