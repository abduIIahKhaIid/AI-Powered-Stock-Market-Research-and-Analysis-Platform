import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import fake_services

from financial_mcp.server import mcp as financial_mcp_server
from financial_mcp.services import set_services
from stock_api import jobs_api, worker
from stock_api.jobs import get_job_store, get_registry
from stock_api.jobs.registry import (
    JobContext,
    JobInputError,
    JobKind,
    build_registry,
    mcp_tool_runner,
    validate_scan,
)
from stock_api.jobs.runner import execute
from stock_api.jobs.store import InvalidTransition, JobStore, MemoryJobStore, PostgresJobStore
from stock_api.main import app


def kind(handler: Any, name: str = "demo") -> JobKind:
    return JobKind(name, "Demo", "analysis", 10, 20, lambda p: p, handler)


# --- store and lifecycle -------------------------------------------------------------


def lifecycle(store: JobStore) -> None:
    job = store.create("demo", {"x": 1}, "c" * 32)
    assert (job.status, job.progress, job.attempts) == ("queued", 0, 0)
    running = store.update(job.id, status="running", progress=150, stage="Working")
    assert running.progress == 100 and running.started_at is not None
    done = store.update(job.id, status="succeeded", result={"answer": 42})
    assert done.finished_at is not None and store.get(job.id).result == {"answer": 42}
    with pytest.raises(InvalidTransition):
        store.update(job.id, status="running")
    other = store.create("demo", {}, None)
    store.update(other.id, status="cancelled")
    assert [j.id for j in store.list(conversation_id="c" * 32)] == [job.id]
    assert [j.id for j in store.list(status="cancelled")] == [other.id]


def test_memory_store_lifecycle() -> None:
    lifecycle(MemoryJobStore())


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a Postgres test database")
def test_postgres_store_lifecycle() -> None:
    import psycopg

    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url) as conn:
        conn.execute("DROP TABLE IF EXISTS analysis_jobs")
    lifecycle(PostgresJobStore(url))


# --- runner --------------------------------------------------------------------------


def test_successful_job_reports_progress_and_saves_its_result() -> None:
    store = MemoryJobStore()
    stages: list[str] = []

    def handler(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        ctx.progress(50, "Half way")
        stages.append(store.get(ctx.job_id).stage)
        return {"double": params["x"] * 2}

    job = store.create("demo", {"x": 21})
    done = execute(job.id, store, {"demo": kind(handler)})
    assert (done.status, done.progress, done.attempts) == ("succeeded", 100, 1)
    assert done.result == {"double": 42} and stages == ["Half way"]


def test_running_a_finished_job_again_does_nothing() -> None:
    store, calls = MemoryJobStore(), []
    job = store.create("demo", {})

    def handler(params: dict[str, Any], ctx: JobContext) -> dict[str, int]:
        calls.append(1)
        return {"n": len(calls)}

    registry = {"demo": kind(handler)}
    execute(job.id, store, registry)
    again = execute(job.id, store, registry)
    assert calls == [1] and again.result == {"n": 1} and again.attempts == 1


def test_failure_is_recorded_on_the_job() -> None:
    store = MemoryJobStore()
    job = store.create("demo", {})

    def boom(params: dict[str, Any], ctx: JobContext) -> None:
        raise ValueError("bad data")

    failed = execute(job.id, store, {"demo": kind(boom)})
    assert failed.status == "failed" and failed.error == "ValueError: bad data"


def test_cancel_before_start_and_while_running() -> None:
    store = MemoryJobStore()
    early = store.create("demo", {})
    store.update(early.id, cancel_requested=True)
    assert execute(early.id, store, {"demo": kind(lambda p, c: 1)}).status == "cancelled"

    job = store.create("demo", {})

    def slow(params: dict[str, Any], ctx: JobContext) -> None:
        ctx.progress(10, "Step 1")
        store.update(ctx.job_id, cancel_requested=True)  # the user presses Cancel
        ctx.progress(20, "Step 2")

    assert execute(job.id, store, {"demo": kind(slow)}).status == "cancelled"


def test_unknown_kind_fails() -> None:
    store = MemoryJobStore()
    job = store.create("nope", {})
    assert execute(job.id, store, {}).error == "Unknown job kind 'nope'."


# --- job kinds -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "non-empty list"),
        ({"symbols": [f"S{i}" for i in range(11)]}, "at most 10"),
        ({"symbols": ["AAPL", "b@d"]}, "Not valid tickers"),
        ({"symbols": ["AAPL"], "period": "max"}, "Unsupported period"),
    ],
)
def test_validate_scan_rejects(params: dict[str, Any], message: str) -> None:
    with pytest.raises(JobInputError, match=message):
        validate_scan(params)


def test_validate_scan_defaults() -> None:
    assert validate_scan({"symbols": ["aapl", "AAPL", "nvda"]}) == {
        "symbols": ["AAPL", "NVDA"],
        "indicators": ["rsi_14", "macd", "sma_50"],
        "period": "6mo",
    }


@pytest.fixture
def market(tmp_path: Path) -> Iterator[None]:
    set_services(fake_services(tmp_path))
    yield
    set_services(None)


def test_indicator_scan_through_the_mcp_server(market: None) -> None:
    registry = build_registry(mcp_tool_runner(financial_mcp_server))
    store = MemoryJobStore()
    scan = registry["indicator_scan"]
    job = store.create(scan.name, scan.validate({"symbols": ["AAPL", "IBM"], "period": "1mo"}))
    done = execute(job.id, store, registry)
    assert done.status == "succeeded"
    assert done.result["rows"]["AAPL"]["last_close"] == 107.1
    assert "not listed on NASDAQ" in done.result["rows"]["IBM"]["error"]
    assert done.result["sources"][0]["source"] == "Fake price source (tests)"


def test_refresh_directory_job(market: None) -> None:
    registry = build_registry(mcp_tool_runner(financial_mcp_server))
    store = MemoryJobStore()
    job = store.create("refresh_directory", {})
    done = execute(job.id, store, registry)
    assert done.status == "succeeded" and done.result["directory_as_of"]


# --- Celery wiring ---------------------------------------------------------------------


def test_jobs_go_to_their_queue_with_time_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(worker.celery_app, "send_task", lambda name, **kw: sent.append((name, kw)))
    job = MemoryJobStore().create("demo", {})
    worker.enqueue(job, kind(lambda p, c: None))
    name, options = sent[0]
    assert name == "jobs.run" and options["task_id"] == job.id
    assert (options["queue"], options["soft_time_limit"], options["time_limit"]) == (
        "analysis",
        10,
        20,
    )


def test_beat_schedules_the_directory_refresh() -> None:
    entry = worker.celery_app.conf.beat_schedule["refresh-symbol-directory"]
    assert entry["task"] == "jobs.scheduled" and entry["args"] == ("refresh_directory",)
    assert set(worker.QUEUES) == {"analysis", "sandbox", "ingest"}


# --- API -------------------------------------------------------------------------------


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str]] = []
        self.revoked: list[str] = []

    def enqueue(self, job: Any, kind: JobKind) -> None:
        self.enqueued.append((job.id, kind.queue))

    def revoke(self, job_id: str) -> None:
        self.revoked.append(job_id)


@pytest.fixture
def api() -> Iterator[tuple[httpx.AsyncClient, MemoryJobStore, FakeQueue]]:
    store, queue = MemoryJobStore(), FakeQueue()
    registry = {"demo": kind(lambda p, c: None)}
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[jobs_api.get_queue] = lambda: queue
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, store, queue
    app.dependency_overrides.clear()


async def test_create_get_cancel_and_list_jobs(api: Any) -> None:
    client, store, queue = api
    created = await client.post("/jobs", json={"kind": "demo", "params": {"x": 1}})
    assert created.status_code == 202
    job = created.json()
    assert job["status"] == "queued" and queue.enqueued == [(job["id"], "analysis")]

    assert (await client.get(f"/jobs/{job['id']}")).json()["params"] == {"x": 1}
    assert (await client.get(f"/jobs/{'0' * 32}")).status_code == 404

    cancelled = await client.post(f"/jobs/{job['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled" and queue.revoked == [job["id"]]
    assert (await client.post(f"/jobs/{job['id']}/cancel")).status_code == 409

    running = store.create("demo", {})
    store.update(running.id, status="running")
    stopping = (await client.post(f"/jobs/{running.id}/cancel")).json()
    assert stopping["status"] == "running" and stopping["cancel_requested"] is True

    listed = (await client.get("/jobs", params={"status": "cancelled"})).json()
    assert [j["id"] for j in listed] == [job["id"]]


async def test_create_job_validation(api: Any) -> None:
    client, _, _ = api
    assert (await client.post("/jobs", json={"kind": "nope"})).status_code == 422
    bad_conversation = {"kind": "demo", "conversation_id": "x"}
    assert (await client.post("/jobs", json=bad_conversation)).status_code == 422
