"""SCRUM-28: Python analysis jobs that run in the sandbox, and the agent tool for them."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from fakes import fake_services

from financial_mcp.server import mcp as financial_mcp_server
from financial_mcp.services import set_services
from stock_api import sandbox_client
from stock_api.agent.job_tools import RUN_PYTHON, START_SCAN, START_SWEEP, JobLauncher, JobToolbox
from stock_api.agent.policy import ToolPolicy
from stock_api.agent.toolbox import ToolOutcome, ToolSpec
from stock_api.jobs.registry import (
    JobInputError,
    TransientJobError,
    build_registry,
    candles_csv,
    mcp_tool_runner,
    report_python,
    validate_python,
)
from stock_api.jobs.runner import execute
from stock_api.jobs.store import Job, JobStore, MemoryJobStore
from stock_api.sandbox_client import SandboxClient, SandboxError

CODE = "import pandas as pd\nresult = {'rows': len(pd.read_csv(INPUT_DIR + '/prices_AAPL.csv'))}"


class FakeSandbox:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, code: str, files: dict[str, str]) -> dict[str, Any]:
        self.calls.append((code, files))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)


@pytest.fixture
def market(tmp_path: Path) -> Any:
    set_services(fake_services(tmp_path))
    yield
    set_services(None)


def registry_with(sandbox: FakeSandbox) -> dict[str, Any]:
    return build_registry(mcp_tool_runner(financial_mcp_server), sandbox)


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({}, "code must be"),
        ({"code": "  "}, "code must be"),
        ({"code": "x" * 20_001}, "at most 20000"),
        ({"code": "result = 1", "symbols": ["A", "B", "C", "D", "E", "F"]}, "at most 5"),
        ({"code": "result = 1", "symbols": ["b@d"]}, "Not valid tickers"),
        ({"code": "result = 1", "period": "10y"}, "Unsupported period"),
    ],
)
def test_validate_python_rejects(params: dict[str, Any], message: str) -> None:
    with pytest.raises(JobInputError, match=message):
        validate_python(params)


def test_validate_python_defaults() -> None:
    assert validate_python({"code": "result = 1", "symbols": ["aapl", "AAPL"]}) == {
        "code": "result = 1",
        "symbols": ["AAPL"],
        "period": "1y",
    }


def test_candles_become_csv() -> None:
    candles = [
        {"time": "2026-11-12", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}
    ]
    assert candles_csv(candles).splitlines() == [
        "date,open,high,low,close,volume",
        "2026-11-12,1.0,2.0,0.5,1.5,10",
    ]


def test_the_job_passes_price_files_to_the_sandbox(market: None) -> None:
    sandbox = FakeSandbox({"ok": True, "result": {"rows": 21}, "stdout": "", "duration_ms": 900})
    registry = registry_with(sandbox)
    kind = registry["python_analysis"]
    assert (kind.queue, kind.title) == ("sandbox", "Python analysis")
    store = MemoryJobStore()
    params = kind.validate({"code": CODE, "symbols": ["AAPL"], "period": "1mo"})
    done = execute(store.create(kind.name, params).id, store, registry)
    assert done.status == "succeeded", done.error
    assert done.result["result"] == {"rows": 21} and done.result["inputs"] == ["prices_AAPL.csv"]
    code, files = sandbox.calls[0]
    assert code == CODE
    assert files["prices_AAPL.csv"].startswith("date,open,high,low,close,volume\n")
    assert done.summary == "Python analysis on AAPL"
    assert "**Python analysis finished** on AAPL (1mo)" in report_python(params, done.result)


def test_a_code_error_fails_the_job_without_retrying(market: None) -> None:
    sandbox = FakeSandbox({"ok": False, "error": "NameError: name 'x' is not defined"})
    registry = registry_with(sandbox)
    store = MemoryJobStore()
    job = store.create("python_analysis", {"code": "result = x", "symbols": [], "period": "1y"})
    failed = execute(job.id, store, registry)
    assert failed.status == "failed" and failed.attempts == 1
    assert failed.error == "SandboxCodeError: NameError: name 'x' is not defined"


def test_an_unreachable_sandbox_is_retried(market: None) -> None:
    sandbox = FakeSandbox(
        TransientJobError("The sandbox could not be reached."), {"ok": True, "result": 1}
    )
    registry = registry_with(sandbox)
    store = MemoryJobStore()
    job = store.create("python_analysis", {"code": "result = 1", "symbols": [], "period": "1y"})
    assert execute(job.id, store, registry).status == "queued"
    assert execute(job.id, store, registry).status == "succeeded"


def test_no_sandbox_means_no_python_jobs() -> None:
    assert "python_analysis" not in build_registry(mcp_tool_runner(financial_mcp_server))


# --- client ----------------------------------------------------------------------------


def test_client_sends_the_token_and_maps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    replies = [
        httpx.Response(200, json={"ok": True, "result": 3}),
        httpx.Response(503),
        httpx.Response(401),
    ]

    def post(url: str, **kwargs: Any) -> httpx.Response:
        seen.append({"url": url, **kwargs})
        reply = replies.pop(0)
        if reply is None:
            raise httpx.ConnectError("refused")
        return reply

    monkeypatch.setattr(sandbox_client.httpx, "post", post)
    client = SandboxClient("http://sandbox:8200/", "tok", 30)
    assert client("result = 3", {"a.csv": "x"}) == {"ok": True, "result": 3}
    assert seen[0]["url"] == "http://sandbox:8200/run"
    assert seen[0]["headers"] == {"X-Sandbox-Token": "tok"}
    assert seen[0]["json"]["timeout_seconds"] == 30 and seen[0]["timeout"] == 60
    with pytest.raises(TransientJobError):
        client("result = 3", {})
    with pytest.raises(SandboxError):
        client("result = 3", {})
    replies.append(None)  # type: ignore[arg-type]
    with pytest.raises(TransientJobError, match="could not be reached"):
        client("result = 3", {})


# --- the agent tool -------------------------------------------------------------------


class Queue:
    """Runs the job right away, as a worker would."""

    def __init__(self, store: JobStore, registry: dict[str, Any]) -> None:
        self.store = store
        self.registry = registry

    def enqueue(self, job: Job, kind: Any) -> None:
        execute(job.id, self.store, self.registry)

    def revoke(self, job_id: str) -> None:
        pass


class EmptyToolbox:
    async def list_tools(self) -> list[ToolSpec]:
        return [ToolSpec("get_quote", "Quote")]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        return ToolOutcome(name, arguments, ok=True, payload={})


def toolbox_for(sandbox: FakeSandbox, wait: float = 5.0) -> JobToolbox:
    store, registry = MemoryJobStore(), registry_with(sandbox)
    launcher = JobLauncher(lambda: store, lambda: registry, Queue(store, registry))  # type: ignore[arg-type]
    return JobToolbox(EmptyToolbox(), launcher, "c" * 32, wait_seconds=wait)


async def test_run_python_waits_for_the_result(market: None) -> None:
    toolbox = toolbox_for(FakeSandbox({"ok": True, "result": {"vol": 0.21}, "stdout": "hi"}))
    names = [spec.name for spec in await toolbox.list_tools()]
    assert names == ["get_quote", START_SCAN, START_SWEEP, RUN_PYTHON]
    outcome = await toolbox.call(RUN_PYTHON, {"code": CODE, "symbols": ["AAPL"], "period": "1mo"})
    assert outcome.ok
    assert outcome.payload["data"] == {"result": {"vol": 0.21}, "stdout": "hi"}
    assert outcome.source == "Python sandbox on Fake price source (tests) price data"
    assert outcome.as_of is not None


async def test_run_python_reports_errors_to_the_model(market: None) -> None:
    toolbox = toolbox_for(FakeSandbox({"ok": False, "error": "Blocked by the safety check: x"}))
    outcome = await toolbox.call(RUN_PYTHON, {"code": "import subprocess"})
    assert not outcome.ok and "Blocked by the safety check" in (outcome.error or "")
    bad = await toolbox.call(RUN_PYTHON, {"code": ""})
    assert not bad.ok and "code must be" in (bad.error or "")


async def test_run_python_does_not_wait_forever() -> None:
    store = MemoryJobStore()
    registry = registry_with(FakeSandbox())

    class Later:
        def enqueue(self, job: Job, kind: Any) -> None:
            pass  # never picked up

    launcher = JobLauncher(lambda: store, lambda: registry, Later())  # type: ignore[arg-type]
    toolbox = JobToolbox(EmptyToolbox(), launcher, "c" * 32, wait_seconds=0.2)
    outcome = await toolbox.call(RUN_PYTHON, {"code": "result = 1"})
    assert not outcome.ok and "still running" in (outcome.error or "")


def test_run_python_needs_approval() -> None:
    needed = ToolPolicy().approval_for(ToolSpec(RUN_PYTHON, ""))
    assert needed is not None and "Python" in needed["reason"]
