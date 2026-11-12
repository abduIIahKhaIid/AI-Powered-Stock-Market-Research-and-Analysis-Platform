"""analysis_jobs: one row per background job (SCRUM-32, SCRUM-77, SCRUM-34).

Status moves queued -> running -> succeeded | failed | cancelled; a queued job can also be
cancelled directly, and a running job goes back to queued while it waits for a retry.
Progress is 0-100 with a short stage text. The job id is the idempotency key for running it;
an optional client idempotency key stops the same request from creating two jobs.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

Status = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
ALLOWED: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "cancelled", "failed"}),
    "running": frozenset({"running", "queued", "succeeded", "failed", "cancelled"}),
}


class JobNotFound(KeyError):
    pass


class InvalidTransition(ValueError):
    pass


class IdempotencyConflict(ValueError):
    """The idempotency key was already used for a different request."""


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    params: dict[str, Any]
    conversation_id: str | None = None
    status: Status = "queued"
    progress: int = 0
    stage: str = "Waiting for a worker"
    attempts: int = 0
    max_attempts: int = 3
    error: str | None = None
    result: Any = None
    result_path: str | None = None
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # When the next attempt starts, while the job waits for a retry.
    retry_at: datetime | None = None
    # Downloadable files saved by the job: [{"name", "bytes", "media_type"}].
    files: list[dict[str, Any]] = field(default_factory=list)
    # One line for the saved analyses list.
    summary: str | None = None
    idempotency_key: str | None = None

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("created_at", "started_at", "finished_at", "retry_at"):
            data[key] = data[key].isoformat() if data[key] else None
        return data


def check_transition(job: Job, status: str) -> None:
    if status != job.status and status not in ALLOWED.get(job.status, frozenset()):
        raise InvalidTransition(f"A {job.status} job cannot become {status}.")


class JobStore(Protocol):
    def create(
        self,
        kind: str,
        params: dict[str, Any],
        conversation_id: str | None = None,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> Job: ...

    def get(self, job_id: str) -> Job: ...

    def find_by_key(self, idempotency_key: str) -> Job | None: ...

    def update(self, job_id: str, **changes: Any) -> Job: ...

    def list(
        self, conversation_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[Job]: ...


def _new(
    kind: str,
    params: dict[str, Any],
    conversation_id: str | None,
    max_attempts: int,
    idempotency_key: str | None,
) -> Job:
    return Job(
        uuid.uuid4().hex,
        kind,
        params,
        conversation_id,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
    )


def _apply(job: Job, changes: dict[str, Any]) -> Job:
    status = changes.get("status")
    if status is not None:
        check_transition(job, status)
        if status == "running":
            changes.setdefault("retry_at", None)
            if job.started_at is None:
                changes.setdefault("started_at", _now())
        if status in TERMINAL:
            changes.setdefault("finished_at", _now())
    if "progress" in changes:
        changes["progress"] = max(0, min(100, int(changes["progress"])))
    return replace(job, **changes)


class MemoryJobStore:
    """In-process store for tests and running without Postgres."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(
        self,
        kind: str,
        params: dict[str, Any],
        conversation_id: str | None = None,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> Job:
        with self._lock:
            if idempotency_key is not None:
                existing = self.find_by_key(idempotency_key)
                if existing is not None:
                    return existing
            job = _new(kind, params, conversation_id, max_attempts, idempotency_key)
            self._jobs[job.id] = job
        return job

    def find_by_key(self, idempotency_key: str) -> Job | None:
        for job in self._jobs.values():
            if job.idempotency_key == idempotency_key:
                return job
        return None

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise JobNotFound(job_id) from None

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._lock:
            job = _apply(self.get(job_id), changes)
            self._jobs[job_id] = job
            return job

    def list(
        self, conversation_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[Job]:
        jobs = [
            j
            for j in self._jobs.values()
            if (conversation_id is None or j.conversation_id == conversation_id)
            and (status is None or j.status == status)
        ]
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)[:limit]


SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    params JSONB NOT NULL,
    conversation_id TEXT,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    result JSONB,
    result_path TEXT,
    cancel_requested BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS analysis_jobs_conversation
    ON analysis_jobs (conversation_id, created_at);
CREATE INDEX IF NOT EXISTS analysis_jobs_status ON analysis_jobs (status, created_at);
-- SCRUM-34: retries, saved files and idempotency keys.
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS files JSONB NOT NULL DEFAULT '[]';
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS summary TEXT;
ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS analysis_jobs_idempotency_key
    ON analysis_jobs (idempotency_key) WHERE idempotency_key IS NOT NULL;
"""

COLUMNS = (
    "id, kind, params, conversation_id, status, progress, stage, attempts, max_attempts, error, "
    "result, result_path, cancel_requested, created_at, started_at, finished_at, retry_at, files, "
    "summary, idempotency_key"
)
COLUMN_NAMES = COLUMNS.split(", ")
JSON_FIELDS = {"params", "result", "files"}


class PostgresJobStore:
    """analysis_jobs in Postgres; safe to share between the API and Celery workers."""

    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._ready = False

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(self._url, connect_timeout=5, row_factory=dict_row)
        if not self._ready:
            conn.execute(SCHEMA)
            conn.commit()
            self._ready = True
        return conn

    @staticmethod
    def _row(row: dict[str, Any]) -> Job:
        return Job(**(row | {"files": row.get("files") or []}))

    def create(
        self,
        kind: str,
        params: dict[str, Any],
        conversation_id: str | None = None,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> Job:
        job = _new(kind, params, conversation_id, max_attempts, idempotency_key)
        values = [
            json.dumps(getattr(job, c), default=str) if c in JSON_FIELDS else getattr(job, c)
            for c in COLUMN_NAMES
        ]
        placeholders = ", ".join(["%s"] * len(COLUMN_NAMES))
        with self._connect() as conn:
            row = conn.execute(
                f"INSERT INTO analysis_jobs ({COLUMNS}) VALUES ({placeholders}) "
                "ON CONFLICT DO NOTHING RETURNING id",
                values,
            ).fetchone()
        if row is None and idempotency_key is not None:
            # Another request with the same key won the race; return its job.
            existing = self.find_by_key(idempotency_key)
            if existing is not None:
                return existing
        return job

    def find_by_key(self, idempotency_key: str) -> Job | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM analysis_jobs WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else self._row(row)

    def get(self, job_id: str) -> Job:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM analysis_jobs WHERE id = %s", (job_id,)
            ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return self._row(row)

    def update(self, job_id: str, **changes: Any) -> Job:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {COLUMNS} FROM analysis_jobs WHERE id = %s FOR UPDATE", (job_id,)
            ).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            current = self._row(row)
            job = _apply(current, dict(changes))
            fields = [c for c in COLUMN_NAMES if getattr(job, c) != getattr(current, c)]
            if fields:
                conn.execute(
                    f"UPDATE analysis_jobs SET {', '.join(f'{c} = %s' for c in fields)} "
                    "WHERE id = %s",
                    [
                        *(
                            json.dumps(getattr(job, c), default=str)
                            if c in JSON_FIELDS
                            else getattr(job, c)
                            for c in fields
                        ),
                        job_id,
                    ],
                )
        return job

    def list(
        self, conversation_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[Job]:
        where, params = [], []
        if conversation_id is not None:
            where.append("conversation_id = %s")
            params.append(conversation_id)
        if status is not None:
            where.append("status = %s")
            params.append(status)
        sql = f"SELECT {COLUMNS} FROM analysis_jobs"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT %s"
        with self._connect() as conn:
            rows = conn.execute(sql, [*params, limit]).fetchall()
        return [self._row(row) for row in rows]
