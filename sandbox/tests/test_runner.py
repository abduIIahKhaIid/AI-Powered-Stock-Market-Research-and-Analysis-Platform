"""The runner and its API, with a fake docker CLI (no containers)."""

import shlex
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from sandbox_runner import app as runner_app
from sandbox_runner.docker_run import DockerSandbox, Limits, parse

FAKE = Path(__file__).with_name("fake_docker.py")


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FAKE_DOCKER_STATE", str(tmp_path))
    return tmp_path


def sandbox(timeout: float = 10.0) -> DockerSandbox:
    return DockerSandbox(
        image="stock-sandbox:test",
        docker=shlex.join([sys.executable, str(FAKE)]),
        limits=Limits(timeout_seconds=timeout),
    )


def test_every_isolation_flag_is_set() -> None:
    command = DockerSandbox(image="stock-sandbox:latest").command("sandbox-x")
    text = " ".join(command)
    for flag in [
        "run --rm --interactive --name sandbox-x",
        "--network none",
        "--read-only",
        "--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m",
        "--tmpfs /input:rw,noexec,nosuid,nodev,size=16m,mode=1777",
        "--user 10001:10001",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--memory 512m --memory-swap 512m",
        "--cpus 1",
        "--pids-limit 128",
    ]:
        assert flag in text
    assert command[-1] == "stock-sandbox:latest"
    assert "-v" not in command and "--volume" not in command and "--privileged" not in command


async def test_a_run_returns_the_result(state: Path) -> None:
    result = await sandbox().run(
        "import os\nresult = {'files': sorted(os.listdir(INPUT_DIR))}", {"a.csv": "x\n1\n"}
    )
    assert result.ok and result.result == {"files": ["a.csv"]} and result.exit_code == 0
    assert result.container.startswith("sandbox-")


async def test_a_long_run_is_stopped_at_the_time_limit(state: Path) -> None:
    result = await sandbox(timeout=1.0).run("while True:\n    pass", {})
    assert result.timed_out and not result.ok
    assert result.error == "The code ran longer than the 1 s limit and was stopped."
    assert (state / "killed.txt").read_text().strip() == result.container
    assert result.duration_ms < 5000


async def test_too_much_output_is_stopped(state: Path) -> None:
    result = await sandbox().run("import os\nwhile True:\n    os.write(1, b'x' * 65536)", {})
    assert not result.ok and "more than 2 MB" in (result.error or "")


async def test_the_sandbox_failing_to_start(state: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_DOCKER_EXIT", "125")
    result = await sandbox().run("result = 1", {})
    assert not result.ok and result.error is not None
    assert result.error.startswith("The sandbox could not start")


def test_parse_explains_crashes() -> None:
    killed = parse(b"", b"", 137, 10, "c")
    assert "512 MB memory limit" in (killed.error or "")
    broken = parse(b"hello\n__SANDBOX_RESULT__ {not json", b"", 1, 10, "c")
    assert broken.error == "The code ended without a result (exit code 1)."
    ok = parse(
        b'noise\n__SANDBOX_RESULT__ {"ok": true, "result": 5, "stdout": "", "error": null}\n',
        b"",
        0,
        3,
        "c",
    )
    assert ok.ok and ok.result == 5


@pytest.fixture
def api(state: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[httpx.AsyncClient]:
    settings = runner_app.Settings()
    settings.token = "s3cret-token"
    runner_app.app.dependency_overrides[runner_app.get_settings] = lambda: settings
    runner_app.app.dependency_overrides[runner_app.get_sandbox] = lambda: sandbox()
    transport = httpx.ASGITransport(app=runner_app.app)
    yield httpx.AsyncClient(transport=transport, base_url="http://sandbox")
    runner_app.app.dependency_overrides.clear()


TOKEN = {"X-Sandbox-Token": "s3cret-token"}


async def test_run_endpoint(api: httpx.AsyncClient) -> None:
    body: dict[str, Any] = {"code": "result = {'sum': 1 + 2}", "files": {"prices_AAPL.csv": "x"}}
    assert (await api.post("/run", json=body)).status_code == 401
    assert (
        await api.post("/run", json=body, headers={"X-Sandbox-Token": "wrong"})
    ).status_code == 401
    answer = (await api.post("/run", json=body, headers=TOKEN)).json()
    assert answer["ok"] is True and answer["result"] == {"sum": 3} and answer["blocked"] == []


async def test_blocked_code_never_starts_a_container(api: httpx.AsyncClient, state: Path) -> None:
    answer = (await api.post("/run", json={"code": "import subprocess"}, headers=TOKEN)).json()
    assert answer["ok"] is False and answer["blocked"] == [
        "line 1: importing subprocess is not allowed"
    ]
    assert answer["error"].startswith("Blocked by the safety check")
    assert not (state / "commands.txt").exists()


@pytest.mark.parametrize(
    "body",
    [
        {"code": ""},
        {"code": "result = 1", "files": {"../etc/passwd": "x"}},
        {"code": "result = 1", "files": {f"f{i}.csv": "x" for i in range(13)}},
        {"code": "result = 1", "timeout_seconds": 31},
    ],
)
async def test_run_rejects_bad_requests(api: httpx.AsyncClient, body: dict[str, Any]) -> None:
    assert (await api.post("/run", json=body, headers=TOKEN)).status_code == 422


async def test_health(api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert (await api.get("/health")).json() == {"status": "ok"}
    assert (await api.get("/health/ready")).json()["image"] == "stock-sandbox:test"
    monkeypatch.setenv("FAKE_DOCKER_IMAGE", "0")
    assert (await api.get("/health/ready")).status_code == 503
