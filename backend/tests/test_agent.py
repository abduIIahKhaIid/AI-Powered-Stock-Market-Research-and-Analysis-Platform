import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import (
    completion,
    connection_error,
    fake_services,
    scripted_gateway,
    text_turn,
    tool_turn,
)

from financial_mcp.server import mcp as financial_mcp_server
from financial_mcp.services import set_services
from stock_api import chat as chat_module
from stock_api.agent import (
    Agent,
    AgentEvent,
    MCPToolbox,
    MemoryConversationStore,
    ToolOutcome,
    ToolPolicy,
)
from stock_api.agent.context import Conversation, build_messages, system_prompt
from stock_api.agent.toolbox import compact_for_model
from stock_api.llm import LLMConfigError, LLMGateway
from stock_api.main import app


@pytest.fixture(autouse=True)
def market(tmp_path: Path) -> Iterator[None]:
    set_services(fake_services(tmp_path))
    yield
    set_services(None)


def in_process_tools() -> Any:
    return MCPToolbox.connect(financial_mcp_server)


def make_agent(
    gateway: LLMGateway,
    store: MemoryConversationStore | None = None,
    **kwargs: Any,
) -> Agent:
    return Agent(
        gateway,
        in_process_tools,
        store or MemoryConversationStore(),
        today=lambda: date(2026, 11, 12),
        **kwargs,
    )


async def run(agent: Agent, message: str, **kwargs: Any) -> list[AgentEvent]:
    return [event async for event in agent.run(message, **kwargs)]


def of_type(events: list[AgentEvent], kind: str) -> list[dict[str, Any]]:
    return [event.data for event in events if event.type == kind]


# --- planner loop ---------------------------------------------------------------------


async def test_question_uses_mcp_tool_and_streams_answer() -> None:
    gateway, llm = scripted_gateway(
        tool_turn(("get_quote", {"symbol": "AAPL"})),
        text_turn("Apple (AAPL) last closed at 107.1 USD (Fake price source, 2026-11-11)."),
    )
    store = MemoryConversationStore()
    events = await run(make_agent(gateway, store), "What is Apple's price?")

    kinds = [event.type for event in events]
    assert kinds[0] == "conversation"
    assert kinds[-2:] == ["sources", "done"]
    assert "tool_call" in kinds and "tool_result" in kinds and "token" in kinds

    result = of_type(events, "tool_result")[0]
    assert result["ok"] is True
    assert result["preview"]["price"] == 107.1
    assert of_type(events, "sources")[0]["sources"] == [
        {"source": "Fake price source (tests)", "as_of": "2026-11-11", "tool": "get_quote"}
    ]
    done = of_type(events, "done")[0]
    assert done["answer"].startswith("Apple (AAPL) last closed at 107.1 USD")
    assert "not financial advice" in done["disclaimer"]
    assert done["usage"]["tool_calls"] == 1 and done["usage"]["llm_calls"] == 2
    streamed = "".join(t["text"] for t in of_type(events, "token"))
    assert streamed == done["answer"]

    first_request, second_request = llm.requests
    tool_names = [tool["function"]["name"] for tool in first_request["tools"]]
    assert "get_quote" in tool_names and "ping" not in tool_names
    tool_message = second_request["messages"][-1]
    assert tool_message["role"] == "tool" and tool_message["tool_call_id"] == "call_0"
    assert '"price": 107.1' in tool_message["content"]

    saved = await store.load(done["conversation_id"])
    assert [m["role"] for m in saved.messages] == ["user", "assistant"]


async def test_non_nasdaq_symbol_error_is_given_to_the_model() -> None:
    gateway, llm = scripted_gateway(
        tool_turn(("get_quote", {"symbol": "IBM"})),
        text_turn("IBM is not listed on NASDAQ, so I can't cover it."),
    )
    events = await run(make_agent(gateway), "IBM price?")
    result = of_type(events, "tool_result")[0]
    assert result["ok"] is False
    assert "not listed on NASDAQ" in result["error"]
    assert "not listed on NASDAQ" in llm.requests[1]["messages"][-1]["content"]
    assert of_type(events, "sources")[0]["sources"] == []


async def test_blocked_or_unknown_tool_is_refused_not_run() -> None:
    gateway, llm = scripted_gateway(
        tool_turn(("ping", {}), ("delete_everything", {})),
        text_turn("Done."),
    )
    events = await run(make_agent(gateway), "hi")
    results = of_type(events, "tool_result")
    assert [r["ok"] for r in results] == [False, False]
    assert all("is not available" in r["error"] for r in results)
    assert of_type(events, "done")[0]["usage"]["tool_calls"] == 0


async def test_tool_budget_stops_extra_calls_and_forces_an_answer() -> None:
    gateway, llm = scripted_gateway(
        tool_turn(("get_quote", {"symbol": "AAPL"}), ("get_quote", {"symbol": "NVDA"})),
        text_turn("Here is what I found for AAPL."),
    )
    events = await run(make_agent(gateway, policy=ToolPolicy(max_tool_calls=1)), "AAPL and NVDA")
    results = of_type(events, "tool_result")
    assert results[0]["ok"] is True
    assert "budget" in results[1]["error"]
    assert "tools" not in llm.requests[1]  # the answer step gets no tools


async def test_last_step_has_no_tools_so_the_loop_always_ends() -> None:
    gateway, llm = scripted_gateway(
        tool_turn(("get_quote", {"symbol": "AAPL"})),
        text_turn("Final answer from gathered data."),
    )
    events = await run(make_agent(gateway, max_steps=2), "loop?")
    assert "tools" in llm.requests[0] and "tools" not in llm.requests[1]
    assert of_type(events, "done")[0]["answer"] == "Final answer from gathered data."


async def test_llm_unreachable_ends_with_error_and_saves_nothing() -> None:
    gateway, _ = scripted_gateway(connection_error())
    store = MemoryConversationStore()
    events = await run(make_agent(gateway, store), "price?")
    assert events[-1].type == "error"
    assert events[-1].data["code"] == "llm_unavailable"
    assert await store.load(events[0].data["conversation_id"]) == Conversation()


async def test_tool_server_unreachable_ends_with_error() -> None:
    @asynccontextmanager
    async def broken() -> AsyncIterator[Any]:
        raise ConnectionError("mcp down")
        yield  # pragma: no cover

    gateway, _ = scripted_gateway()
    agent = Agent(gateway, broken, MemoryConversationStore())
    events = await run(agent, "price?")
    assert events[-1].type == "error"
    assert events[-1].data["code"] == "tools_unavailable"
    assert "ConnectionError: mcp down" in events[-1].data["message"]


async def test_mcp_server_down_reports_the_real_cause() -> None:
    gateway, _ = scripted_gateway()
    agent = Agent(
        gateway,
        lambda: MCPToolbox.connect("http://127.0.0.1:9/mcp", timeout=2),
        MemoryConversationStore(),
    )
    events = await run(agent, "price?")
    assert events[-1].data["code"] == "tools_unavailable"
    assert "ExceptionGroup" not in events[-1].data["message"]


async def test_follow_up_sees_history_and_old_turns_are_summarized() -> None:
    gateway, llm = scripted_gateway(
        text_turn("AAPL answer."),
        text_turn("NVDA answer."),
        completion("User asked about AAPL; assistant answered."),  # summary call
    )
    store = MemoryConversationStore()
    agent = make_agent(gateway, store, history_messages=2)
    first = await run(agent, "Tell me about AAPL")
    conversation_id = first[0].data["conversation_id"]
    await run(agent, "and NVDA?", conversation_id=conversation_id)

    second_request_roles = [m["role"] for m in llm.requests[1]["messages"]]
    assert second_request_roles == ["system", "user", "assistant", "user"]
    saved = await store.load(conversation_id)
    assert saved.summary == "User asked about AAPL; assistant answered."
    assert [m["content"] for m in saved.messages] == ["and NVDA?", "NVDA answer."]
    messages = build_messages(saved, "next", "simple", date(2026, 11, 12))
    assert "Summary of the earlier conversation" in messages[1]["content"]


def test_system_prompt_modes_and_rules() -> None:
    simple = system_prompt("simple", date(2026, 11, 12))
    detailed = system_prompt("detailed", date(2026, 11, 12))
    assert "2026-11-12" in simple and "NASDAQ-listed securities only" in simple
    assert "SIMPLE" in simple and "DETAILED" in detailed
    assert "buy, sell or hold" in simple


def test_long_tool_results_keep_the_latest_items() -> None:
    candles = [{"date": f"2026-01-{i:02d}", "close": float(i)} for i in range(1, 400)]
    outcome = ToolOutcome(
        "get_price_history",
        {},
        ok=True,
        payload={"data": {"symbol": "AAPL", "candles": candles}, "source": "s", "as_of": "d"},
    )
    text = compact_for_model(outcome, max_chars=2000)
    data = json.loads(text)
    assert len(text) <= 2000
    assert data["data"]["candles"][-1]["close"] == 399.0
    assert "of 399" in data["truncated"]["candles"]


# --- SSE ------------------------------------------------------------------------------


async def test_sse_stream_formats_events_and_sends_keepalive() -> None:
    async def slow() -> AsyncIterator[AgentEvent]:
        yield AgentEvent("status", {"step": 1})
        await asyncio.sleep(0.05)
        yield AgentEvent("done", {"answer": "ok"})

    chunks = [c async for c in chat_module.sse_stream(slow(), keepalive_seconds=0.01)]
    assert chunks[0] == 'event: status\ndata: {"step": 1}\n\n'
    assert ": keep-alive\n\n" in chunks
    assert chunks[-1] == 'event: done\ndata: {"answer": "ok"}\n\n'


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines:
            events.append((lines["event"], json.loads(lines["data"])))
    return events


@pytest.fixture
def client() -> Iterator[httpx.AsyncClient]:
    yield httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def test_chat_endpoint_streams_events(client: httpx.AsyncClient) -> None:
    gateway, _ = scripted_gateway(
        tool_turn(("get_quote", {"symbol": "AAPL"})), text_turn("AAPL is at 107.1 USD.")
    )
    app.dependency_overrides[chat_module.agent_dependency] = lambda: make_agent(gateway)
    response = await client.post("/chat", json={"message": "AAPL price?", "mode": "detailed"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert events[0][0] == "conversation" and events[0][1]["mode"] == "detailed"
    assert events[-1][0] == "done"
    assert events[-1][1]["answer"] == "AAPL is at 107.1 USD."


async def test_chat_rejects_empty_message_and_bad_conversation_id(
    client: httpx.AsyncClient,
) -> None:
    gateway, _ = scripted_gateway()
    app.dependency_overrides[chat_module.agent_dependency] = lambda: make_agent(gateway)
    assert (await client.post("/chat", json={"message": ""})).status_code == 422
    bad = await client.post("/chat", json={"message": "hi", "conversation_id": "../x"})
    assert bad.status_code == 422


async def test_chat_returns_503_when_llm_not_configured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def not_configured() -> Agent:
        raise LLMConfigError("LLM model is not set")

    monkeypatch.setattr(chat_module, "get_agent", not_configured)
    response = await client.post("/chat", json={"message": "hi"})
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]
