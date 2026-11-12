"""Where job results live (SCRUM-34).

Small results stay in the job row (JSONB). Large results and files such as CSV exports are
written under one folder per job: a local volume in development; an S3 bucket can take its
place in production behind the same interface.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Protocol

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

RESULT_FILE = "result.json"


class ResultFileError(ValueError):
    """A job id or file name that could leave the results folder."""


class ResultStore(Protocol):
    def write(self, job_id: str, name: str, data: bytes) -> int: ...

    def read(self, job_id: str, name: str) -> bytes: ...

    def path(self, job_id: str, name: str) -> Path: ...

    def clear(self, job_id: str) -> None: ...


def check_name(name: str) -> str:
    if not _FILE_NAME.match(name) or ".." in name:
        raise ResultFileError(f"Not a valid result file name: {name!r}.")
    return name


class LocalResultStore:
    """Files under <root>/<job id>/<name>; atomic writes, so a retry never leaves half a file."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _folder(self, job_id: str) -> Path:
        if not _JOB_ID.match(job_id):
            raise ResultFileError(f"Not a valid job id: {job_id!r}.")
        return self.root / job_id

    def path(self, job_id: str, name: str) -> Path:
        return self._folder(job_id) / check_name(name)

    def write(self, job_id: str, name: str, data: bytes) -> int:
        target = self.path(job_id, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(f".{target.name}.partial")
        partial.write_bytes(data)
        os.replace(partial, target)
        return len(data)

    def read(self, job_id: str, name: str) -> bytes:
        return self.path(job_id, name).read_bytes()

    def clear(self, job_id: str) -> None:
        """Remove what an earlier attempt left behind, so a retry starts clean."""
        shutil.rmtree(self._folder(job_id), ignore_errors=True)


def store_result(
    job_id: str, result: Any, results: ResultStore | None, inline_max_bytes: int
) -> tuple[Any, str | None]:
    """Return (value for the job row, result_path). Large results go to a file."""
    data = json.dumps(result, default=str).encode()
    if results is None or len(data) <= inline_max_bytes:
        return result, None
    results.write(job_id, RESULT_FILE, data)
    return {"stored_in_file": RESULT_FILE, "bytes": len(data)}, f"{job_id}/{RESULT_FILE}"


def load_result(job_id: str, inline: Any, result_path: str | None, results: ResultStore) -> Any:
    if result_path is None:
        return inline
    return json.loads(results.read(job_id, RESULT_FILE))
