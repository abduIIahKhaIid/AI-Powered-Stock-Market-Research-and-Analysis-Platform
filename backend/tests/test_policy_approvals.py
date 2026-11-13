import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fakes import scripted_gateway, text_turn, tool_turn

from stock_api.agent import Agent, AgentEvent, MemoryConversationStore, ToolOutcome, ToolSpec
from stock_api.agent.approvals import ApprovalBroker
from stock_api.agent.audit import MemoryAuditLog, PostgresAuditLog, tool_call_params
from stock_api.agent.factory import get_approval_broker
from stock_api.agent.policy import ToolPolicy, validate_arguments
from stock_api.llm import ToolCall
from stock_api.main import app

# --- argument validation and rules ---------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"symbol": "AAPL", "period": "6mo", "interval": "1d", "years": 5}, None),
        ({"symbol": "../etc"}, "not a valid ticker"),
        ({"symbols": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"]}, "at most 5"),
        ({"symbols": ["AAPL", "D R O P"]}, "Not valid ticker"),
        ({"period": "50y"}, "Unsupported period"),
        ({"interval": "1s"}, "Unsupported interval"),
        ({"years": 40}, "between 1 and 10"),
        ({"indicators": ["sma"] * 11}, "at most 10"),
    ],
)
def test_validate_arguments(arguments: dict[str, Any], message: str | None) -> None:
    result = validate_arguments(arguments)
    if message is None:
        assert result is None
    else:
        assert result is not None and message in result


def test_policy_rejects_bad_arguments_before_the_tool_runs() -> None:
    call = ToolCall(id="c", name="get_quote", arguments={"symbol": "IBM; DROP"})
    refusal = ToolPolicy().refusal(call, 0, {"get_quote"})
    assert refusal is not None and "rejected" in refusal


def test_which_tools_need_approval() -> None:
    policy = ToolPolicy(approval_tools=frozenset({"get_earnings"}))
    assert policy.approval_for(ToolSpec("get_quote", "")) is None
    for name, words in [
        ("run_python_analysis", "Python"),
        ("start_job_backtest", "background job"),
        ("export_csv", "Exports"),
    ]:
        needed = policy.approval_for(ToolSpec(name, ""))
        assert needed is not None and words in needed["reason"]
    assert policy.approval_for(ToolSpec("get_earnings", "")) is not None
    paid = ToolSpec("av_quote", "", approval={"reason": "Paid API call", "estimate": "$0.01"})
    assert policy.approval_for(paid) == {"reason": "Paid API call", "estimate": "$0.01"}


# --- the approval flow in the agent --------------------------------------------------


class FakeToolbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec("get_quote", "Quote"), ToolSpec("run_python_analysis", "Run code")]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        return ToolOutcome(
            name, arguments, ok=True, payload={"data": {"result": 42.0}, "source": "sandbox"}
        )


def make_agent(
    toolbox: FakeToolbox, broker: ApprovalBroker | None, audit: MemoryAuditLog, *turns: Any
) -> tuple[Agent, Any]:
    gateway, llm = scripted_gateway(*turns)

    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeToolbox]:
        yield toolbox

    agent = Agent(gateway, factory, MemoryConversationStore(), approvals=broker, audit=audit)
    return agent, llm


CODE_TURN = tool_turn(("run_python_analysis", {"code": "print(6 * 7)"}))


async def run_with_decision(
    agent: Agent, broker: ApprovalBroker, approve: bool | None
) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    async for event in agent.run("Backtest AAPL"):
        events.append(event)
        if event.type == "approval_required" and approve is not None:
            broker.decide(event.data["approval_id"], approve=approve)
    return events


async def test_approved_action_runs_and_is_audited() -> None:
    toolbox, audit, broker = FakeToolbox(), MemoryAuditLog(), ApprovalBroker(5)
    agent, _ = make_agent(toolbox, broker, audit, CODE_TURN, text_turn("The result is 42.0."))
    events = await run_with_decision(agent, broker, approve=True)

    required = next(e.data for e in events if e.type == "approval_required")
    assert required["tool"] == "run_python_analysis"
    assert required["arguments"] == {"code": "print(6 * 7)"}
    assert "Python" in required["reason"]
    assert next(e.data for e in events if e.type == "approval_result")["status"] == "approved"
    assert toolbox.calls == [("run_python_analysis", {"code": "print(6 * 7)"})]
    assert [a["status"] for a in audit.approvals] == ["pending", "approved"]
    assert audit.tool_calls[0]["ok"] is True
    assert audit.tool_calls[0]["approval_id"] == required["approval_id"]


async def test_denied_action_does_not_run_and_the_model_is_told() -> None:
    toolbox, audit, broker = FakeToolbox(), MemoryAuditLog(), ApprovalBroker(5)
    agent, llm = make_agent(toolbox, broker, audit, CODE_TURN, text_turn("I did not run it."))
    events = await run_with_decision(agent, broker, approve=False)

    assert toolbox.calls == []
    assert next(e.data for e in events if e.type == "approval_result")["status"] == "denied"
    assert "declined" in llm.requests[1]["messages"][-1]["content"]
    assert audit.tool_calls[0]["ok"] is False
    assert [a["status"] for a in audit.approvals] == ["pending", "denied"]


async def test_unanswered_request_expires() -> None:
    toolbox, audit, broker = FakeToolbox(), MemoryAuditLog(), ApprovalBroker(0.05)
    agent, llm = make_agent(toolbox, broker, audit, CODE_TURN, text_turn("No answer, not run."))
    events = await run_with_decision(agent, broker, approve=None)
    assert next(e.data for e in events if e.type == "approval_result")["status"] == "expired"
    assert toolbox.calls == []
    assert "no answer" in llm.requests[1]["messages"][-1]["content"]


async def test_closing_the_stream_while_waiting_expires_the_request() -> None:
    toolbox, audit, broker = FakeToolbox(), MemoryAuditLog(), ApprovalBroker(30)
    agent, _ = make_agent(toolbox, broker, audit, CODE_TURN, text_turn("unused"))
    approval_id = None

    async def consume() -> None:
        nonlocal approval_id
        async for event in agent.run("Backtest"):
            if event.type == "approval_required":
                approval_id = event.data["approval_id"]

    task = asyncio.create_task(consume())
    while approval_id is None:
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert broker.get(approval_id).status == "expired"
    assert toolbox.calls == []


async def test_without_a_broker_sensitive_actions_are_refused() -> None:
    toolbox, audit = FakeToolbox(), MemoryAuditLog()
    agent, _ = make_agent(toolbox, None, audit, CODE_TURN, text_turn("Not available."))
    events = [e async for e in agent.run("Backtest")]
    assert "approval_required" not in [e.type for e in events]
    assert toolbox.calls == []


async def test_every_tool_call_is_audited_including_refusals() -> None:
    toolbox, audit, broker = FakeToolbox(), MemoryAuditLog(), ApprovalBroker(5)
    agent, _ = make_agent(
        toolbox,
        broker,
        audit,
        tool_turn(("get_quote", {"symbol": "AAPL"}), ("get_quote", {"symbol": "B@D"})),
        text_turn("Done."),
    )
    [e async for e in agent.run("quotes")]
    assert [(r["tool"], r["ok"]) for r in audit.tool_calls] == [
        ("get_quote", True),
        ("get_quote", False),
    ]
    assert "rejected" in audit.tool_calls[1]["error"]


# --- POST /approvals/{id} ---------------------------------------------------------------


async def test_approval_endpoint() -> None:
    broker = ApprovalBroker(5)
    app.dependency_overrides[get_approval_broker] = lambda: broker
    request = broker.open("c" * 32, "run_python_analysis", {}, "Runs code.")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            ok = await client.post(f"/approvals/{request.id}", json={"decision": "approve"})
            again = await client.post(f"/approvals/{request.id}", json={"decision": "deny"})
            missing = await client.post(f"/approvals/{'0' * 32}", json={"decision": "deny"})
            invalid = await client.post(f"/approvals/{request.id}", json={"decision": "maybe"})
    finally:
        app.dependency_overrides.clear()
    assert ok.status_code == 200
    assert ok.json() == {
        "approval_id": request.id,
        "tool": "run_python_analysis",
        "status": "approved",
    }
    assert again.status_code == 409
    assert missing.status_code == 404
    assert invalid.status_code == 422


# --- Postgres audit log ------------------------------------------------------------------


def test_tool_call_params_serialise_arguments() -> None:
    params = tool_call_params(
        {"conversation_id": "c", "tool": "get_quote", "arguments": {"symbol": "AAPL"}, "ok": True}
    )
    assert params[:5] == ("c", None, "get_quote", '{"symbol": "AAPL"}', True)


async def test_postgres_audit_failure_does_not_raise() -> None:
    audit = PostgresAuditLog("postgresql://nobody:nothing@127.0.0.1:9/none")
    await audit.tool_call({"conversation_id": "c", "tool": "t", "arguments": {}, "ok": True})


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a Postgres test database")
async def test_postgres_audit_writes_rows() -> None:
    import psycopg

    url = os.environ["TEST_DATABASE_URL"]
    audit = PostgresAuditLog(url)
    broker = ApprovalBroker(5)
    request = broker.open("d" * 32, "run_python_analysis", {"x": 1}, "Runs code.")
    await audit.approval(request)
    broker.decide(request.id, approve=True)
    await audit.approval(request)
    await audit.tool_call(
        {
            "conversation_id": "d" * 32,
            "tool": "t",
            "arguments": {},
            "ok": True,
            "approval_id": request.id,
        }
    )
    async with await psycopg.AsyncConnection.connect(url) as conn:
        row = await (
            await conn.execute("SELECT status FROM approvals WHERE id = %s", (request.id,))
        ).fetchone()
        assert row == ("approved",)


async def test_the_approval_card_gets_the_toolbox_estimate() -> None:
    class EstimatingToolbox(FakeToolbox):
        def estimate(self, name: str, arguments: dict[str, Any]) -> str | None:
            return "Up to 30 s. No cost."

    toolbox, audit, broker = EstimatingToolbox(), MemoryAuditLog(), ApprovalBroker(5)
    agent, _ = make_agent(toolbox, broker, audit, CODE_TURN, text_turn("Done: 42.0."))
    events = await run_with_decision(agent, broker, approve=True)
    required = next(e.data for e in events if e.type == "approval_required")
    assert required["estimate"] == "Up to 30 s. No cost."
    done = events[-1].data
    assert done["projection"] is False
