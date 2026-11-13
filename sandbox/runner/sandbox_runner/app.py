"""Internal HTTP API of the Sandbox Runner (SCRUM-70).

Only the Celery worker calls it, over the internal ``sandbox`` network, with a shared token.
This service is the only one that mounts the Docker socket.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from .docker_run import DockerSandbox, Limits, RunResult
from .precheck import MAX_CODE_CHARS, check

logger = logging.getLogger("sandbox_runner")

FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_FILES = 12
MAX_INPUT_BYTES = 8_000_000


class Settings:
    def __init__(self) -> None:
        self.image = os.environ.get("SANDBOX_IMAGE", "stock-sandbox:latest")
        self.docker = os.environ.get("SANDBOX_DOCKER", "docker")
        self.token = os.environ.get("SANDBOX_TOKEN", "")
        self.max_concurrent = int(os.environ.get("SANDBOX_MAX_CONCURRENT", "2"))
        self.timeout_seconds = float(os.environ.get("SANDBOX_TIMEOUT_SECONDS", "30"))


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_sandbox() -> DockerSandbox:
    settings = get_settings()
    return DockerSandbox(
        image=settings.image,
        docker=settings.docker,
        limits=Limits(timeout_seconds=settings.timeout_seconds),
    )


@lru_cache
def get_slots() -> asyncio.Semaphore:
    return asyncio.Semaphore(get_settings().max_concurrent)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        removed = await get_sandbox().cleanup()
        if removed:
            logger.info("removed %s sandbox containers left from an earlier run", removed)
    except OSError as exc:  # docker CLI missing: /health/ready reports it
        logger.warning("could not clean up sandbox containers: %s", exc)
    yield


app = FastAPI(title="Sandbox Runner", version="0.1.0", lifespan=lifespan)


def require_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_sandbox_token: Annotated[str | None, Header()] = None,
) -> None:
    if settings.token and not hmac.compare_digest(x_sandbox_token or "", settings.token):
        raise HTTPException(status_code=401, detail="Missing or wrong sandbox token.")


class RunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    files: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, gt=0, le=30)

    @field_validator("files")
    @classmethod
    def check_files(cls, files: dict[str, str]) -> dict[str, str]:
        if len(files) > MAX_FILES:
            raise ValueError(f"at most {MAX_FILES} input files")
        bad = [name for name in files if not FILE_NAME.match(name)]
        if bad:
            raise ValueError(f"not valid file names: {', '.join(bad)}")
        if sum(len(text.encode()) for text in files.values()) > MAX_INPUT_BYTES:
            raise ValueError(f"input files are larger than {MAX_INPUT_BYTES // 1_000_000} MB")
        return files


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(sandbox: Annotated[DockerSandbox, Depends(get_sandbox)]) -> dict[str, Any]:
    try:
        image = await sandbox.image_ready()
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"docker is not available: {exc}") from None
    if not image:
        raise HTTPException(status_code=503, detail=f"sandbox image {sandbox.image} is missing")
    return {"status": "ok", "image": sandbox.image}


@app.post("/run", dependencies=[Depends(require_token)])
async def run(
    body: RunRequest,
    sandbox: Annotated[DockerSandbox, Depends(get_sandbox)],
    slots: Annotated[asyncio.Semaphore, Depends(get_slots)],
) -> dict[str, Any]:
    problems = check(body.code)
    if problems:
        blocked = RunResult(ok=False, error="Blocked by the safety check: " + "; ".join(problems))
        return blocked.to_dict() | {"blocked": problems}
    async with slots:
        result = await sandbox.run(body.code, body.files, body.timeout_seconds)
    logger.info(
        "run %s ok=%s exit=%s timed_out=%s %s ms",
        result.container,
        result.ok,
        result.exit_code,
        result.timed_out,
        result.duration_ms,
    )
    return result.to_dict() | {"blocked": []}
