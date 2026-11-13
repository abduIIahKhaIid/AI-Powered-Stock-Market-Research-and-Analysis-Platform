"""Start one locked-down container per run (SCRUM-70).

Every run gets a fresh container from the sandbox image with no network, a read-only root
filesystem, small tmpfs folders for /tmp and /input, a non-root user, no capabilities,
no-new-privileges, 512 MB of memory, 1 CPU, at most 128 processes and a wall-clock limit.
The code and its input files go in on stdin; the result comes back as one JSON line.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shlex
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

MARKER = "__SANDBOX_RESULT__ "
MAX_OUTPUT_BYTES = 2_000_000


@dataclass(frozen=True)
class Limits:
    memory: str = "512m"
    cpus: str = "1"
    pids: int = 128
    timeout_seconds: float = 30.0
    tmp_size: str = "64m"
    input_size: str = "16m"


@dataclass(frozen=True)
class RunResult:
    ok: bool
    result: Any = None
    stdout: str = ""
    error: str | None = None
    exit_code: int | None = None
    timed_out: bool = False
    duration_ms: int = 0
    container: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DockerSandbox:
    image: str = "stock-sandbox:latest"
    docker: str = "docker"
    limits: Limits = field(default_factory=Limits)

    def command(self, name: str) -> list[str]:
        """The docker run command; every isolation flag is set here and only here."""
        lim = self.limits
        return [
            *shlex.split(self.docker),
            "run",
            "--rm",
            "--interactive",
            "--name",
            name,
            "--label",
            "stock-platform.sandbox=1",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={lim.tmp_size}",
            "--tmpfs",
            f"/input:rw,noexec,nosuid,nodev,size={lim.input_size},mode=1777",
            "--user",
            "10001:10001",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--memory",
            lim.memory,
            "--memory-swap",
            lim.memory,
            "--cpus",
            lim.cpus,
            "--pids-limit",
            str(lim.pids),
            "--ulimit",
            "nofile=256:256",
            "--ulimit",
            "core=0",
            "--stop-timeout",
            "1",
            self.image,
        ]

    async def run(
        self, code: str, files: dict[str, str], timeout_seconds: float | None = None
    ) -> RunResult:
        name = f"sandbox-{uuid.uuid4().hex[:16]}"
        timeout = min(timeout_seconds or self.limits.timeout_seconds, self.limits.timeout_seconds)
        payload = json.dumps({"code": code, "files": files}).encode()
        started = time.perf_counter()

        def elapsed() -> int:
            return int((time.perf_counter() - started) * 1000)

        proc = await asyncio.create_subprocess_exec(
            *self.command(name),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdin and proc.stdout and proc.stderr
        too_big = False

        async def feed() -> None:
            assert proc.stdin
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                proc.stdin.write(payload)
                await proc.stdin.drain()
                proc.stdin.close()

        async def read_stdout() -> bytes:
            nonlocal too_big
            assert proc.stdout
            chunks: list[bytes] = []
            size = 0
            while chunk := await proc.stdout.read(65536):
                size += len(chunk)
                if size > MAX_OUTPUT_BYTES:
                    too_big = True
                    await self._kill(name)
                    # Keep reading to the end: the process only counts as finished once
                    # its pipes are closed, and a full pipe would stop that.
                    while await proc.stdout.read(65536):
                        pass
                    break
                chunks.append(chunk)
            return b"".join(chunks)

        async def read_stderr() -> bytes:
            assert proc.stderr
            return (await proc.stderr.read(MAX_OUTPUT_BYTES))[-4000:]

        work = asyncio.gather(feed(), read_stdout(), read_stderr(), proc.wait())
        timed_out = False
        try:
            _, out, err, exit_code = await asyncio.wait_for(work, timeout)
        except TimeoutError:
            timed_out = True
            await self._kill(name)
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            return RunResult(
                ok=False,
                error=f"The code ran longer than the {timeout:g} s limit and was stopped.",
                exit_code=proc.returncode,
                timed_out=True,
                duration_ms=elapsed(),
                container=name,
            )
        if too_big:
            return RunResult(
                ok=False,
                error=f"The code printed more than {MAX_OUTPUT_BYTES // 1_000_000} MB and was "
                "stopped.",
                exit_code=exit_code,
                duration_ms=elapsed(),
                container=name,
            )
        return parse(out, err, exit_code, elapsed(), name, timed_out)

    async def cleanup(self) -> int:
        """Remove sandbox containers left behind by an earlier runner process."""
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(self.docker),
            "ps",
            "-aq",
            "--filter",
            "label=stock-platform.sandbox=1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        ids = out.decode().split()
        if ids:
            rm = await asyncio.create_subprocess_exec(
                *shlex.split(self.docker),
                "rm",
                "-f",
                *ids,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await rm.wait()
        return len(ids)

    async def image_ready(self) -> bool:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(self.docker),
            "image",
            "inspect",
            self.image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await proc.wait() == 0

    async def _kill(self, name: str) -> None:
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(self.docker),
            "kill",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(proc.wait(), 10)


def parse(
    out: bytes, err: bytes, exit_code: int, duration_ms: int, name: str, timed_out: bool = False
) -> RunResult:
    """Read the harness's result line; explain a crash when there is none."""
    envelope: dict[str, Any] | None = None
    for line in reversed(out.decode(errors="replace").splitlines()):
        if line.startswith(MARKER):
            with contextlib.suppress(json.JSONDecodeError):
                envelope = json.loads(line[len(MARKER) :])
            break
    if envelope is not None:
        return RunResult(
            ok=bool(envelope.get("ok")),
            result=envelope.get("result"),
            stdout=str(envelope.get("stdout") or ""),
            error=envelope.get("error"),
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=duration_ms,
            container=name,
        )
    if exit_code == 137:
        message = "The code was stopped: it went over the 512 MB memory limit or was killed."
    elif exit_code in (125, 126, 127):
        detail = err.decode(errors="replace").strip().splitlines()
        message = f"The sandbox could not start: {detail[-1] if detail else f'exit {exit_code}'}"
    else:
        message = f"The code ended without a result (exit code {exit_code})."
    return RunResult(
        ok=False, error=message, exit_code=exit_code, duration_ms=duration_ms, container=name
    )
