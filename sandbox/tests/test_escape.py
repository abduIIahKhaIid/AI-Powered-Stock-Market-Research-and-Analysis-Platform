"""Escape tests against real containers (SCRUM-71).

They run only with Docker and the sandbox image available:
    docker build -t stock-sandbox:test sandbox/image
    SANDBOX_DOCKER_TESTS=1 SANDBOX_IMAGE=stock-sandbox:test pytest sandbox/tests/test_escape.py

The code here goes straight to the container, skipping the static pre-check, so each test
shows that the container limit alone holds.
"""

import asyncio
import os

import pytest

from sandbox_runner.docker_run import DockerSandbox, Limits

pytestmark = pytest.mark.skipif(
    os.getenv("SANDBOX_DOCKER_TESTS") != "1", reason="needs Docker and the sandbox image"
)


def sandbox(timeout: float = 30.0) -> DockerSandbox:
    image = os.environ.get("SANDBOX_IMAGE", "stock-sandbox:test")
    return DockerSandbox(image=image, limits=Limits(timeout_seconds=timeout))


async def left_over(name: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-aq", "--filter", f"name={name}", stdout=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    return out.decode().strip()


async def test_runs_as_an_unprivileged_user() -> None:
    code = """
import os
lines = open("/proc/self/status").read().splitlines()
status = dict(line.split(":\\t", 1) for line in lines if ":\\t" in line)
result = {
    "uid": os.getuid(),
    "cap_eff": status["CapEff"].strip(),
    "no_new_privs": status["NoNewPrivs"].strip(),
    "seccomp": status["Seccomp"].strip(),
}
"""
    run = await sandbox().run(code, {})
    assert run.ok, run.error
    assert run.result == {
        "uid": 10001,
        "cap_eff": "0000000000000000",
        "no_new_privs": "1",
        "seccomp": "2",
    }
    assert await left_over(run.container) == ""


async def test_no_network() -> None:
    code = """
import socket
attempts = {}
for name, target in [("ip", ("1.1.1.1", 53)), ("dns", ("pypi.org", 443))]:
    try:
        socket.create_connection(target, timeout=3).close()
        attempts[name] = "connected"
    except OSError as exc:
        attempts[name] = type(exc).__name__
interfaces = [line.split(":")[0].strip() for line in open("/proc/net/dev").read().splitlines()[2:]]
result = {"attempts": attempts, "interfaces": interfaces}
"""
    run = await sandbox().run(code, {})
    assert run.ok, run.error
    assert "connected" not in run.result["attempts"].values()
    assert run.result["interfaces"] == ["lo"]


async def test_cannot_write_outside_tmp() -> None:
    code = """
outcome = {}
paths = ["/etc/evil", "/opt/sandbox/harness.py", "/usr/local/lib/evil.py", "/evil"]
for path in paths + ["/tmp/ok.txt", "/input/ok.csv"]:
    try:
        with open(path, "a") as f:
            f.write("x")
        outcome[path] = "written"
    except OSError as exc:
        outcome[path] = type(exc).__name__
try:
    with open("/tmp/big.bin", "wb") as f:
        f.write(b"0" * 100_000_000)
    outcome["tmp_100mb"] = "written"
except OSError as exc:
    outcome["tmp_100mb"] = type(exc).__name__
result = outcome
"""
    run = await sandbox().run(code, {})
    assert run.ok, run.error
    assert run.result["/tmp/ok.txt"] == "written" and run.result["/input/ok.csv"] == "written"
    for path in ["/etc/evil", "/opt/sandbox/harness.py", "/usr/local/lib/evil.py", "/evil"]:
        assert run.result[path] in {"OSError", "PermissionError"}, path
    assert run.result["tmp_100mb"] == "OSError"  # the 64 MB tmpfs is full


async def test_process_limit_stops_a_fork_bomb() -> None:
    code = """
import os, time
made, error = 0, None
try:
    for _ in range(1000):
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        made += 1
except OSError as exc:
    error = type(exc).__name__
result = {"made": made, "error": error}
"""
    run = await sandbox().run(code, {})
    assert run.ok, run.error
    assert run.result["error"] == "BlockingIOError" and run.result["made"] < 128
    assert await left_over(run.container) == ""


async def test_classic_fork_bomb_is_contained() -> None:
    code = "import os\nwhile True:\n    try:\n        os.fork()\n    except OSError:\n        pass"
    run = await sandbox(timeout=5).run(code, {})
    assert not run.ok and run.timed_out
    await asyncio.sleep(2)
    assert await left_over(run.container) == ""


async def test_endless_loop_is_stopped_at_the_wall_clock_limit() -> None:
    run = await sandbox(timeout=3).run("while True:\n    pass", {})
    assert run.timed_out and not run.ok
    assert run.duration_ms < 10_000
    await asyncio.sleep(2)
    assert await left_over(run.container) == ""


async def test_memory_limit() -> None:
    run = await sandbox().run("block = bytearray(1024 * 1024 * 1024)\nresult = len(block)", {})
    assert not run.ok
    assert run.exit_code == 137 or "MemoryError" in (run.error or "")


async def test_analysis_libraries_work_on_input_files() -> None:
    closes = [100 + (i % 7) - (i % 3) for i in range(60)]
    csv = "date,close\n" + "\n".join(
        f"2026-09-{(i % 28) + 1:02d},{c}" for i, c in enumerate(closes)
    )
    code = """
import numpy as np, pandas as pd, scipy.stats as st
from ta.momentum import RSIIndicator
prices = pd.read_csv(INPUT_DIR + "/prices_AAPL.csv")
rsi = RSIIndicator(prices["close"], window=14).rsi()
result = {
    "rows": len(prices),
    "rsi": round(float(rsi.iloc[-1]), 2),
    "mean": float(np.mean(prices["close"])),
    "skew": float(st.skew(prices["close"])),
}
"""
    run = await sandbox().run(code, {"prices_AAPL.csv": csv})
    assert run.ok, run.error
    assert run.result["rows"] == 60 and 0 <= run.result["rsi"] <= 100
