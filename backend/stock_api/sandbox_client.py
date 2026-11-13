"""Client for the Sandbox Runner's internal API, used by the Celery worker (SCRUM-28)."""

from __future__ import annotations

from typing import Any

import httpx

from .jobs.registry import TransientJobError


class SandboxError(RuntimeError):
    """The sandbox refused the request (for example a wrong token)."""


class SandboxClient:
    def __init__(self, url: str, token: str = "", timeout_seconds: float = 30.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def __call__(self, code: str, files: dict[str, str]) -> dict[str, Any]:
        """Run code with its input files; returns {ok, result, stdout, error, ...}."""
        headers = {"X-Sandbox-Token": self.token} if self.token else {}
        body = {"code": code, "files": files, "timeout_seconds": self.timeout_seconds}
        try:
            response = httpx.post(
                f"{self.url}/run",
                json=body,
                headers=headers,
                # Container start-up and clean-up come on top of the run's own limit.
                timeout=self.timeout_seconds + 30,
            )
        except httpx.TransportError as exc:
            raise TransientJobError(f"The sandbox could not be reached ({exc}).") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientJobError(f"The sandbox answered {response.status_code}.")
        if response.status_code != 200:
            raise SandboxError(f"The sandbox refused the run ({response.status_code}).")
        data: dict[str, Any] = response.json()
        return data
