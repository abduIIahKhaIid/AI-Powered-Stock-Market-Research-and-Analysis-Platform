"""SCRUM-34: retries with backoff, idempotency and saved results."""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import fake_services

from financial_mcp.server import mcp as financial_mcp_server
from financial_mcp.services import set_services
from stock_api import jobs_api, worker
from stock_api.agent.toolbox import ToolOutcome
from stock_api.jobs import get_job_store, get_registry, get_result_store
from stock_api.jobs.registry import (
    JobContext,
    JobKind,
    TransientJobError,
    build_registry,
    is_transient_message,
    mcp_tool_runner,
)
from stock_api.jobs.results import LocalResultStore, ResultFileError, load_result
from stock_api.jobs.runner import execute, retry_countdown, retry_delay
from stock_api.jobs.store import JobStore, MemoryJobStore, PostgresJobStore
from stock_api.main import app

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)


def kind(handler: Any, name: str = "demo", **extra: Any) -> JobKind:
    return JobKind(name, "Demo analysis", "analysis", 10, 20, lambda p: p, handler, **extra)


def flaky(failures: int, exc: Exception) -> Any:
    calls: list[int] = []

    def handler(params: dict[str, Any], ctx: JobContext) -> dict[str, int]:
        calls.append(ctx.attempt)
        if len(calls) <= failures:
            raise exc
        return {"attempt": ctx.attempt}

    return handler, calls


# --- retries ---------------------------------------------------------------------------


def test_backoff_doubles_and_is_capped() -> None:
    assert [retry_delay(n, 5, 30) for n in (1, 2, 3, 4)] == [5.0, 10.0, 20.0, 30.0]


def test_temporary_errors_are_retried_with_backoff() -> None:
    store = MemoryJobStore()
    handler, calls = flaky(2, TransientJobError("rate limited"))
    registry = {"demo": kind(handler)}
    job = store.create("demo", {})

    first = execute(job.id, store, registry, now=lambda: NOW)
    assert (first.status, first.attempts) == ("queued", 1)
    assert first.stage == "Retrying 2 of 3 in 5 s"
    assert first.error == "TransientJobError: rate limited"
    assert first.retry_at == NOW + timedelta(seconds=5)
    assert retry_countdown(first, NOW + timedelta(seconds=2)) == 3.0

    second = execute(job.id, store, registry, now=lambda: NOW)
    assert second.stage == "Retrying 3 of 3 in 10 s"

    third = execute(job.id, store, registry, now=lambda: NOW)
    assert (third.status, third.attempts, third.result) == ("succeeded", 3, {"attempt": 3})
    assert third.retry_at is None and third.error is None
    assert calls == [1, 2, 3] and retry_countdown(third) is None


@pytest.mark.parametrize("exc", [ConnectionError("reset"), TimeoutError("slow")])
def test_network_errors_count_as_temporary(exc: Exception) -> None:
    store = MemoryJobStore()
    handler, _ = flaky(1, exc)
    job = store.create("demo", {})
    assert execute(job.id, store, {"demo": kind(handler)}).status == "queued"


def test_gives_up_after_the_last_attempt() -> None:
    store = MemoryJobStore()
    handler, calls = flaky(99, TransientJobError("503 from provider"))
    registry = {"demo": kind(handler)}
    job = store.create("demo", {}, max_attempts=3)
    for _ in range(3):
        last = execute(job.id, store, registry)
    assert last.status == "failed" and calls == [1, 2, 3]
    assert last.error == "Gave up after 3 attempts. TransientJobError: 503 from provider"
    assert execute(job.id, store, registry).attempts == 3  # finished jobs never run again


def test_other_errors_are_not_retried() -> None:
    store = MemoryJobStore()
    handler, calls = flaky(1, KeyError("missing column"))
    job = store.create("demo", {})
    assert execute(job.id, store, {"demo": kind(handler)}).status == "failed" and calls == [1]


def test_cancel_while_waiting_for_a_retry() -> None:
    store = MemoryJobStore()
    handler, calls = flaky(1, TransientJobError("timeout"))
    registry = {"demo": kind(handler)}
    job = store.create("demo", {})
    execute(job.id, store, registry)
    store.update(job.id, status="cancelled", cancel_requested=True)
    assert execute(job.id, store, registry).status == "cancelled" and calls == [1]


@pytest.mark.parametrize(
    ("text", "transient"),
    [
        ("429 Too Many Requests", True),
        ("Rate limit reached, try again later", True),
        ("ConnectError: [Errno 111] Connection refused", True),
        ("Read timed out", True),
        ("503 Service Unavailable", True),
        ("IBM is not listed on NASDAQ.", False),
        ("Unknown indicator 'foo'.", False),
        (None, False),
    ],
)
def test_transient_tool_errors(text: str | None, transient: bool) -> None:
    assert is_transient_message(text) is transient


def test_check_raises_for_temporary_tool_errors_except_on_the_last_attempt() -> None:
    store = MemoryJobStore()
    job = store.create("demo", {})
    busy = ToolOutcome.failure("get_quote", {}, "429 Too Many Requests")
    missing = ToolOutcome.failure("get_quote", {}, "ZZZZ is not listed on NASDAQ.")
    with pytest.raises(TransientJobError, match="get_quote: 429"):
        JobContext(store, job.id, attempt=1, max_attempts=3).check(busy)
    last = JobContext(store, job.id, attempt=3, max_attempts=3)
    assert last.check(busy) is busy
    assert JobContext(store, job.id, attempt=1, max_attempts=3).check(missing) is missing


# --- saved results ---------------------------------------------------------------------


def test_small_results_stay_in_the_row_and_large_ones_go_to_a_file(tmp_path: Path) -> None:
    store, results = MemoryJobStore(), LocalResultStore(tmp_path)
    registry = {"demo": kind(lambda p, c: {"rows": ["x" * 50] * p["n"]})}

    small = execute(store.create("demo", {"n": 1}).id, store, registry, results)
    assert small.result == {"rows": ["x" * 50]} and small.result_path is None

    big = execute(
        store.create("demo", {"n": 100}).id, store, registry, results, inline_max_bytes=1000
    )
    assert big.result == {"stored_in_file": "result.json", "bytes": 5410}
    assert big.result_path == f"{big.id}/result.json"
    assert load_result(big.id, big.result, big.result_path, results)["rows"][99] == "x" * 50


def test_a_retry_replaces_files_instead_of_adding_to_them(tmp_path: Path) -> None:
    store, results = MemoryJobStore(), LocalResultStore(tmp_path)

    def handler(params: dict[str, Any], ctx: JobContext) -> dict[str, str]:
        ctx.save_file(f"attempt-{ctx.attempt}.csv", "a,b\n", "text/csv")
        ctx.save_file("report.csv", f"attempt {ctx.attempt}\n", "text/csv")
        ctx.save_file("report.csv", f"attempt {ctx.attempt} final\n", "text/csv")
        if ctx.attempt == 1:
            raise TransientJobError("network blip")
        return {"ok": "yes"}

    registry = {"demo": kind(handler)}
    job = store.create("demo", {})
    execute(job.id, store, registry, results)
    done = execute(job.id, store, registry, results)
    assert done.status == "succeeded"
    assert [f["name"] for f in done.files] == ["attempt-2.csv", "report.csv"]
    assert sorted(p.name for p in (tmp_path / job.id).iterdir()) == ["attempt-2.csv", "report.csv"]
    assert results.read(job.id, "report.csv") == b"attempt 2 final\n"


@pytest.mark.parametrize(
    ("job_id", "name"),
    [("a" * 32, "../secrets.txt"), ("a" * 32, ".hidden"), ("../x", "result.json")],
)
def test_result_paths_cannot_leave_the_folder(tmp_path: Path, job_id: str, name: str) -> None:
    with pytest.raises(ResultFileError):
        LocalResultStore(tmp_path).path(job_id, name)


@pytest.fixture
def market(tmp_path: Path) -> Iterator[None]:
    set_services(fake_services(tmp_path / "market"))
    yield
    set_services(None)


def test_indicator_scan_saves_a_csv_and_a_summary(market: None, tmp_path: Path) -> None:
    registry = build_registry(mcp_tool_runner(financial_mcp_server))
    store, results = MemoryJobStore(), LocalResultStore(tmp_path / "results")
    scan = registry["indicator_scan"]
    params = scan.validate({"symbols": ["AAPL", "IBM"], "indicators": ["rsi_14"], "period": "1mo"})
    done = execute(store.create(scan.name, params).id, store, registry, results)
    assert done.summary == "rsi_14 for AAPL, IBM (1mo)"
    assert done.files[0]["name"] == "indicator_scan.csv"
    lines = results.read(done.id, "indicator_scan.csv").decode().splitlines()
    assert lines[0] == "symbol,last_bar,last_close,rsi_14,signals,error"
    assert lines[1].startswith("AAPL,") and "107.1" in lines[1]
    assert lines[2].startswith("IBM,") and "not listed on NASDAQ" in lines[2]


# --- Celery wiring ---------------------------------------------------------------------


def test_worker_requeues_a_job_that_waits_for_a_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryJobStore()
    job = store.create("demo", {})
    store.update(job.id, status="running")
    waiting = store.update(
        job.id, status="queued", retry_at=datetime.now(UTC) + timedelta(seconds=10)
    )
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(worker, "run_attempt", lambda job_id: waiting)
    monkeypatch.setattr(worker, "get_registry", lambda: {"demo": kind(lambda p, c: None)})
    monkeypatch.setattr(worker.celery_app, "send_task", lambda name, **kw: sent.append(kw))
    assert worker.run_job.run(job.id) == "queued"
    assert sent[0]["task_id"] == job.id and sent[0]["queue"] == "analysis"
    assert 8 < sent[0]["countdown"] <= 10


# --- API -------------------------------------------------------------------------------


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued: list[str] = []

    def enqueue(self, job: Any, kind: JobKind) -> None:
        self.enqueued.append(job.id)

    def revoke(self, job_id: str) -> None:
        pass


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[httpx.AsyncClient, MemoryJobStore, Any, FakeQueue]]:
    store, queue, results = MemoryJobStore(), FakeQueue(), LocalResultStore(tmp_path)

    def report(params: dict[str, Any], ctx: JobContext) -> dict[str, Any]:
        ctx.save_file("report.csv", "symbol,close\nAAPL,107.1\n", "text/csv")
        return {"rows": list(range(params.get("n", 3)))}

    registry = {"demo": kind(report, summarize=lambda p, r: f"{len(r['rows'])} rows")}
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_result_store] = lambda: results
    app.dependency_overrides[jobs_api.get_queue] = lambda: queue
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield client, store, (registry, results), queue
    app.dependency_overrides.clear()


async def test_idempotency_key_returns_the_first_job(api: Any) -> None:
    client, _, _, queue = api
    headers = {"Idempotency-Key": "scan-2026-11-12-aapl"}
    first = await client.post("/jobs", json={"kind": "demo", "params": {"n": 1}}, headers=headers)
    again = await client.post("/jobs", json={"kind": "demo", "params": {"n": 1}}, headers=headers)
    assert (first.status_code, again.status_code) == (202, 200)
    assert first.json()["id"] == again.json()["id"] and queue.enqueued == [first.json()["id"]]

    other = await client.post("/jobs", json={"kind": "demo", "params": {"n": 2}}, headers=headers)
    assert other.status_code == 409
    bad = await client.post("/jobs", json={"kind": "demo"}, headers={"Idempotency-Key": "x"})
    assert bad.status_code == 422


async def test_results_files_and_saved_analyses(api: Any) -> None:
    client, store, (registry, results), _ = api
    pending = store.create("demo", {"n": 2})
    assert (await client.get(f"/jobs/{pending.id}/result")).status_code == 409

    done = execute(pending.id, store, registry, results, inline_max_bytes=5)
    assert done.result_path is not None  # too big for the row in this test
    body = (await client.get(f"/jobs/{done.id}/result")).json()
    assert body["result"] == {"rows": [0, 1]} and body["job"]["status"] == "succeeded"

    csv = await client.get(f"/jobs/{done.id}/files/report.csv")
    assert csv.status_code == 200 and csv.text == "symbol,close\nAAPL,107.1\n"
    assert csv.headers["content-type"].startswith("text/csv")
    assert 'filename="report.csv"' in csv.headers["content-disposition"]
    assert (await client.get(f"/jobs/{done.id}/files/other.csv")).status_code == 404

    store.update(store.create("demo", {}).id, status="cancelled")
    saved = (await client.get("/analyses")).json()
    assert [(a["id"], a["title"], a["summary"]) for a in saved] == [
        (done.id, "Demo analysis", "2 rows")
    ]
    assert saved[0]["files"][0]["name"] == "report.csv"


# --- Postgres ----------------------------------------------------------------------------


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a Postgres test database")
def test_postgres_upgrade_retries_files_and_idempotency() -> None:
    import psycopg

    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url) as conn:
        conn.execute("DROP TABLE IF EXISTS analysis_jobs")
        # The SCRUM-32 table, before the SCRUM-34 columns existed.
        conn.execute(
            "CREATE TABLE analysis_jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "params JSONB NOT NULL, conversation_id TEXT, status TEXT NOT NULL, "
            "progress INTEGER NOT NULL DEFAULT 0, stage TEXT NOT NULL DEFAULT '', "
            "attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, "
            "error TEXT, result JSONB, result_path TEXT, "
            "cancel_requested BOOLEAN NOT NULL DEFAULT false, created_at TIMESTAMPTZ NOT NULL, "
            "started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ)"
        )
    store: JobStore = PostgresJobStore(url)
    first = store.create("demo", {"n": 1}, idempotency_key="key-123456")
    assert store.create("demo", {"n": 1}, idempotency_key="key-123456").id == first.id
    assert store.find_by_key("key-123456") == first and store.find_by_key("nope-1234") is None

    store.update(first.id, status="running")
    waiting = store.update(first.id, status="queued", retry_at=NOW, stage="Retrying 2 of 3")
    assert store.get(first.id).retry_at == NOW == waiting.retry_at
    store.update(first.id, status="running")
    files = [{"name": "a.csv", "bytes": 4, "media_type": "text/csv"}]
    done = store.update(first.id, status="succeeded", files=files, summary="1 row")
    assert store.get(first.id) == done and done.retry_at is None
    assert json.loads(json.dumps(store.list(status="succeeded")[0].files)) == files
