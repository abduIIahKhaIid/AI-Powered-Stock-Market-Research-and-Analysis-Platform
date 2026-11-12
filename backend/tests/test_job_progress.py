"""SCRUM-33: live job progress over pub/sub and SSE, jobs started from the chat, reports."""

import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import scripted_gateway, text_turn, tool_turn

from stock_api import job_events_api, worker
from stock_api.agent import Agent, AgentEvent, MemoryConversationStore, ToolOutcome, ToolSpec
from stock_api.agent.approvals import ApprovalBroker
from stock_api.agent.context import remember_job_report
from stock_api.agent.job_tools import START_SCAN, JobLauncher, JobToolbox
from stock_api.agent.policy import ToolPolicy
from stock_api.jobs import get_job_store, get_registry, get_result_store
from stock_api.jobs.events import MemoryEvents, PublishingJobStore, progress_payload
from stock_api.jobs.registry import JobContext, JobKind, TransientJobError, report_scan
from stock_api.jobs.reporting import done_payload, report_text
from stock_api.jobs.results import LocalResultStore
from stock_api.jobs.runner import execute
from stock_api.jobs.store import Job, MemoryJobStore
from stock_api.llm import ToolCall
from stock_api.main import app

SCAN_RESULT = {
    "symbols": ["AAPL", "IBM"],
    "indicators": ["rsi_14", "macd"],
    "period": "6mo",
    "rows": {
        "AAPL": {
            "last_close": 231.456,
            "last_bar": "2026-11-11T00:00:00",
            "latest": {"rsi_14": {"rsi_14": 61.237}, "macd": {"macd": 1.5, "signal": 1.25}},
            "signals": ["RSI 14 is between 30 and 70"],
        },
        "IBM": {"error": "IBM is not listed on NASDAQ."},
    },
    "sources": [{"source": "Yahoo Finance (yfinance)", "as_of": "2026-11-11"}],
}


def scan_kind(handler: Any = None) -> JobKind:
    return JobKind(
        "indicator_scan",
        "Indicator scan",
        "analysis",
        10,
        20,
        lambda p: p,
        handler or (lambda p, c: SCAN_RESULT),
        summarize=lambda p, r: "rsi_14, macd for AAPL, IBM (6mo)",
        report=report_scan,
    )


# --- publishing ------------------------------------------------------------------------


def test_every_update_is_published_and_a_publish_failure_is_harmless() -> None:
    sent: list[dict[str, Any]] = []
    store = PublishingJobStore(MemoryJobStore(), lambda job: sent.append(progress_payload(job)))
    job = store.create("demo", {}, "c" * 32)
    store.update(job.id, status="running", progress=40, stage="Computing AAPL")
    assert [(m["status"], m["progress"], m["stage"]) for m in sent] == [
        ("running", 40, "Computing AAPL")
    ]
    assert sent[0]["conversation_id"] == "c" * 32

    def broken(job: Job) -> None:
        raise ConnectionError("redis down")

    flaky = PublishingJobStore(MemoryJobStore(), broken)
    other = flaky.create("demo", {})
    assert flaky.update(other.id, status="running").status == "running"


# --- the relay -------------------------------------------------------------------------


def parse(chunks: list[str]) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for chunk in chunks:
        if chunk.startswith(":"):
            continue
        head, data = chunk.strip().split("\n", 1)
        events.append((head.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


async def test_progress_reaches_the_stream_within_a_second(tmp_path: Path) -> None:
    events = MemoryEvents()
    store = PublishingJobStore(MemoryJobStore(), events.publish)
    registry = {"indicator_scan": scan_kind()}
    job = store.create("indicator_scan", {"symbols": ["AAPL", "IBM"]}, "c" * 32)
    stream = job_events_api.relay(
        job.id, store, registry, LocalResultStore(tmp_path), events.subscribe, 30.0
    )
    first = parse([await anext(stream)])
    assert first == [("job_progress", progress_payload(job) | {"title": "Indicator scan"})]

    # The worker reports progress from another thread.
    started = time.perf_counter()
    threading.Thread(
        target=store.update, args=(job.id,), kwargs={"status": "running", "progress": 50}
    ).start()
    (name, data), *_ = parse([await asyncio.wait_for(anext(stream), 1.0)])
    assert time.perf_counter() - started < 1.0
    assert (name, data["status"], data["progress"]) == ("job_progress", "running", 50)

    store.update(job.id, status="succeeded", result=SCAN_RESULT, summary="2 symbols")
    rest = parse([chunk async for chunk in stream])
    assert [name for name, _ in rest] == ["job_progress", "job_done"]
    done = rest[-1][1]
    assert done["status"] == "succeeded" and done["title"] == "Indicator scan"
    assert "**AAPL**: last close 231.46 on 2026-11-11" in done["report"]


async def test_a_missed_message_is_caught_by_polling(tmp_path: Path) -> None:
    events = MemoryEvents()
    inner = MemoryJobStore()  # changes made here are not published
    job = inner.create("indicator_scan", {})
    inner.update(job.id, status="running")
    stream = job_events_api.relay(
        job.id, inner, {}, LocalResultStore(tmp_path), events.subscribe, 0.05
    )
    await anext(stream)
    assert await anext(stream) == ": keep-alive\n\n"
    inner.update(job.id, status="failed", error="ValueError: bad data")
    rest = parse([chunk async for chunk in stream])
    assert rest[-1][1]["report"] == "The indicator_scan did not finish: ValueError: bad data"


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[httpx.AsyncClient, MemoryJobStore, LocalResultStore]]:
    store, results, events = MemoryJobStore(), LocalResultStore(tmp_path), MemoryEvents()
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_registry] = lambda: {"indicator_scan": scan_kind()}
    app.dependency_overrides[get_result_store] = lambda: results
    app.dependency_overrides[job_events_api.event_source_dependency] = lambda: events.subscribe
    app.dependency_overrides[job_events_api.get_poll_seconds] = lambda: 0.05
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, store, results
    app.dependency_overrides.clear()


async def test_events_endpoint_for_a_finished_job(api: Any) -> None:
    client, store, results = api
    job = store.create("indicator_scan", {"symbols": ["AAPL", "IBM"]})
    execute(job.id, store, {"indicator_scan": scan_kind()}, results)
    response = await client.get(f"/jobs/{job.id}/events")
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse([c + "\n\n" for c in response.text.split("\n\n") if c.strip()])
    assert [name for name, _ in events] == ["job_progress", "job_done"]
    assert events[0][1]["progress"] == 100 and events[1][1]["summary"].startswith("rsi_14")
    assert (await client.get(f"/jobs/{'0' * 32}/events")).status_code == 404


# --- reports ---------------------------------------------------------------------------


def test_scan_report_copies_the_figures() -> None:
    assert report_scan({}, SCAN_RESULT).splitlines() == [
        "**Indicator scan finished** for AAPL, IBM (period 6mo).",
        "- **AAPL**: last close 231.46 on 2026-11-11; rsi_14 61.24; macd (macd 1.50, signal "
        "1.25). Signals: RSI 14 is between 30 and 70.",
        "- **IBM**: IBM is not listed on NASDAQ.",
        "",
        "Source: Yahoo Finance (yfinance), as of 2026-11-11.",
        "The full table and the CSV file are under Saved analyses.",
    ]


def test_reports_for_cancelled_and_large_results(tmp_path: Path) -> None:
    store, results = MemoryJobStore(), LocalResultStore(tmp_path)
    kind = scan_kind()
    big = execute(
        store.create(kind.name, {}).id, store, {kind.name: kind}, results, inline_max_bytes=10
    )
    assert big.result_path is not None
    assert "**AAPL**" in done_payload(big, kind, results)["report"]

    stopped = store.create(kind.name, {})
    stopped = store.update(stopped.id, status="cancelled")
    assert (
        report_text(stopped, kind, results)
        == "The indicator scan was cancelled before it finished."
    )


def test_on_finish_runs_once_when_the_job_ends() -> None:
    store = MemoryJobStore()
    finished: list[Job] = []
    calls: list[int] = []

    def handler(params: dict[str, Any], ctx: JobContext) -> dict[str, int]:
        calls.append(ctx.attempt)
        if ctx.attempt == 1:
            raise TransientJobError("timeout")
        return {"ok": 1}

    kind = scan_kind(handler)
    job = store.create(kind.name, {})
    for _ in range(3):
        execute(job.id, store, {kind.name: kind}, on_finish=finished.append)
    assert calls == [1, 2] and [j.status for j in finished] == ["succeeded"]


async def test_the_report_joins_the_conversation_history() -> None:
    conversations = MemoryConversationStore()
    await remember_job_report(conversations, "c" * 32, "Scan finished.", keep_messages=2)
    await remember_job_report(conversations, "c" * 32, "Second scan finished.", keep_messages=2)
    await remember_job_report(conversations, "c" * 32, "Third.", keep_messages=2)
    history = (await conversations.load("c" * 32)).messages
    assert [m["content"] for m in history] == ["Second scan finished.", "Third."]


def test_worker_posts_the_report_to_the_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[tuple[str, str]] = []

    async def remember(store: Any, conversation_id: str, text: str, **kw: Any) -> None:
        posted.append((conversation_id, text))

    monkeypatch.setattr(worker, "remember_job_report", remember)
    monkeypatch.setattr(worker, "get_registry", lambda: {"indicator_scan": scan_kind()})
    store = MemoryJobStore()
    job = store.create("indicator_scan", {}, "c" * 32)
    store.update(job.id, status="running")
    worker.post_report(store.update(job.id, status="cancelled"))
    worker.post_report(store.update(store.create("indicator_scan", {}).id, status="cancelled"))
    assert posted == [("c" * 32, "The indicator scan was cancelled before it finished.")]


# --- starting a job from the chat -----------------------------------------------------


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []

    def enqueue(self, job: Job, kind: JobKind) -> None:
        self.enqueued.append((job.id, kind.queue))

    def revoke(self, job_id: str) -> None:
        pass


class QuoteToolbox:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec("get_quote", "Quote")]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append(name)
        return ToolOutcome(name, arguments, ok=True, payload={"price": 1.0})


def launcher_for(store: MemoryJobStore, queue: FakeQueue) -> JobLauncher:
    from stock_api.jobs.registry import validate_scan

    kind = JobKind("indicator_scan", "Indicator scan", "analysis", 10, 20, validate_scan, print)
    return JobLauncher(lambda: store, lambda: {"indicator_scan": kind}, queue)  # type: ignore[arg-type]


async def test_job_toolbox_adds_the_scan_tool_and_queues_jobs() -> None:
    store, queue, inner = MemoryJobStore(), FakeQueue(), QuoteToolbox()
    toolbox = JobToolbox(inner, launcher_for(store, queue), "c" * 32)
    assert [s.name for s in await toolbox.list_tools()] == ["get_quote", START_SCAN]

    outcome = await toolbox.call(START_SCAN, {"symbols": ["aapl", "MSFT", "NVDA"]})
    assert outcome.ok and outcome.payload["title"] == "Indicator scan"
    job = store.get(outcome.payload["job_id"])
    assert job.params["symbols"] == ["AAPL", "MSFT", "NVDA"] and job.conversation_id == "c" * 32
    assert queue.enqueued == [(job.id, "analysis")]

    bad = await toolbox.call(START_SCAN, {"symbols": ["b@d"]})
    assert not bad.ok and "Not valid tickers" in (bad.error or "")
    assert (await toolbox.call("get_quote", {"symbol": "AAPL"})).ok and inner.calls == ["get_quote"]


def test_job_tools_may_cover_ten_symbols_and_need_approval() -> None:
    ten = [f"SYM{i}" for i in range(10)]
    policy = ToolPolicy()
    scan = ToolCall(id="1", name=START_SCAN, arguments={"symbols": ten})
    compare = ToolCall(id="2", name="compare_stocks", arguments={"symbols": ten})
    assert policy.refusal(scan, 0, {START_SCAN, "compare_stocks"}) is None
    assert "at most 5" in (policy.refusal(compare, 0, {START_SCAN, "compare_stocks"}) or "")
    assert policy.approval_for(ToolSpec(START_SCAN, "")) is not None


async def test_the_agent_starts_a_job_after_approval() -> None:
    store, queue, inner = MemoryJobStore(), FakeQueue(), QuoteToolbox()
    launcher = launcher_for(store, queue)
    gateway, _ = scripted_gateway(
        tool_turn((START_SCAN, {"symbols": ["AAPL", "MSFT", "NVDA"]})),
        text_turn("Scan shuru ho gaya hai; progress neeche dikhega."),
    )

    @asynccontextmanager
    async def factory() -> AsyncIterator[QuoteToolbox]:
        yield inner

    broker = ApprovalBroker(5)
    agent = Agent(
        gateway,
        factory,
        MemoryConversationStore(),
        approvals=broker,
        toolbox_wrapper=lambda toolbox, cid: JobToolbox(toolbox, launcher, cid),
    )
    events: list[AgentEvent] = []
    async for event in agent.run("AAPL, MSFT aur NVDA ka scan karo", conversation_id="c" * 32):
        events.append(event)
        if event.type == "approval_required":
            broker.decide(event.data["approval_id"], approve=True)
    started = next(e.data for e in events if e.type == "job_started")
    assert started["title"] == "Indicator scan" and started["conversation_id"] == "c" * 32
    assert queue.enqueued == [(started["job_id"], "analysis")]
    assert events[-1].type == "done"


# --- Redis ------------------------------------------------------------------------------


@pytest.mark.skipif(not os.getenv("TEST_REDIS_URL"), reason="needs a Redis test server")
async def test_redis_pubsub_round_trip() -> None:
    from stock_api.jobs.events import RedisEventSource, RedisPublisher

    url = os.environ["TEST_REDIS_URL"]
    store = PublishingJobStore(MemoryJobStore(), RedisPublisher(url))
    job = store.create("demo", {})
    async with RedisEventSource(url)(job.id) as subscription:
        assert await subscription.next(0.05) is None
        await asyncio.to_thread(store.update, job.id, status="running", progress=30)
        message = await subscription.next(1.0)
    assert message is not None and (message["id"], message["progress"]) == (job.id, 30)
