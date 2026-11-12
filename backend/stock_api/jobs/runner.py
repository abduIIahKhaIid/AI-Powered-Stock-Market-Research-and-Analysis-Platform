"""Runs one job attempt from start to finish; used by the Celery task and by tests.

SCRUM-32: lifecycle, cancellation and time limits.
SCRUM-34: retries with exponential backoff for temporary errors, and saved results. The job
id is the idempotency key: a finished job is never run again, and a retry first clears the
files an earlier attempt left, so results are never duplicated.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .registry import JobCancelled, JobContext, JobKind, is_transient
from .results import ResultStore, store_result
from .store import Job, JobStore

logger = logging.getLogger("stock_api.jobs")

DEFAULT_INLINE_MAX_BYTES = 64 * 1024


def _too_long(exc: BaseException) -> bool:
    try:
        from celery.exceptions import SoftTimeLimitExceeded
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, SoftTimeLimitExceeded)


def retry_delay(attempt: int, base: float = 5.0, cap: float = 120.0) -> float:
    """Seconds to wait after failed attempt `attempt` (1-based): base, 2x base, 4x base..."""
    return float(min(cap, base * 2 ** (attempt - 1)))


def execute(
    job_id: str,
    store: JobStore,
    registry: dict[str, JobKind],
    results: ResultStore | None = None,
    *,
    inline_max_bytes: int = DEFAULT_INLINE_MAX_BYTES,
    retry_base: float = 5.0,
    retry_cap: float = 120.0,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_finish: Callable[[Job], None] | None = None,
) -> Job:
    """Run one attempt. A job left queued with retry_at set is waiting for its next attempt.

    `on_finish` is called once, when this call moves the job to a final status.
    """
    job = store.get(job_id)
    if job.done:
        return job
    finished = _attempt(job, store, registry, results, inline_max_bytes, retry_base, retry_cap, now)
    if finished.done and on_finish is not None:
        try:
            on_finish(finished)
        except Exception:  # noqa: BLE001 - the job itself is done; reporting is best effort
            logger.exception("on_finish failed for job %s", job_id)
    return finished


def _attempt(
    job: Job,
    store: JobStore,
    registry: dict[str, JobKind],
    results: ResultStore | None,
    inline_max_bytes: int,
    retry_base: float,
    retry_cap: float,
    now: Callable[[], datetime],
) -> Job:
    job_id = job.id
    if job.cancel_requested:
        return store.update(job_id, status="cancelled", stage="Cancelled before it started")
    kind = registry.get(job.kind)
    if kind is None:
        return store.update(job_id, status="failed", error=f"Unknown job kind '{job.kind}'.")

    attempt = job.attempts + 1
    if results is not None:
        results.clear(job_id)
    job = store.update(
        job_id,
        status="running",
        attempts=attempt,
        stage="Starting" if attempt == 1 else f"Attempt {attempt} of {job.max_attempts}",
        error=None,
    )
    ctx = JobContext(store, job_id, attempt, job.max_attempts, results)
    try:
        result: Any = kind.handler(job.params, ctx)
    except JobCancelled:
        return store.update(job_id, status="cancelled", stage="Cancelled")
    except Exception as exc:  # noqa: BLE001 - recorded on the job, not raised to Celery
        return _failed(store, job, kind, exc, attempt, retry_base, retry_cap, now)

    stored, result_path = store_result(job_id, result, results, inline_max_bytes)
    summary = kind.summarize(job.params, result) if kind.summarize else None
    return store.update(
        job_id,
        status="succeeded",
        progress=100,
        stage="Done",
        result=stored,
        result_path=result_path,
        files=ctx.files,
        summary=summary,
    )


def _failed(
    store: JobStore,
    job: Job,
    kind: JobKind,
    exc: Exception,
    attempt: int,
    retry_base: float,
    retry_cap: float,
    now: Callable[[], datetime],
) -> Job:
    if _too_long(exc):
        message = f"Took longer than the {kind.soft_limit} s limit for this job."
        transient = False
    else:
        message = f"{type(exc).__name__}: {exc}"
        transient = is_transient(exc)

    if transient and attempt < job.max_attempts:
        delay = retry_delay(attempt, retry_base, retry_cap)
        logger.info(
            "job %s attempt %s failed, retrying in %.0f s: %s", job.id, attempt, delay, message
        )
        return store.update(
            job.id,
            status="queued",
            stage=f"Retrying {attempt + 1} of {job.max_attempts} in {delay:.0f} s",
            error=message,
            retry_at=now() + timedelta(seconds=delay),
        )
    if transient:
        message = f"Gave up after {attempt} attempts. {message}"
    logger.warning("job %s (%s) failed: %s", job.id, job.kind, message)
    return store.update(job.id, status="failed", stage="Failed", error=message)


def retry_countdown(job: Job, now: datetime | None = None) -> float | None:
    """Seconds until the next attempt when the job is waiting for a retry, else None."""
    if job.status != "queued" or job.retry_at is None:
        return None
    current = now or datetime.now(UTC)
    return max(0.0, (job.retry_at - current).total_seconds())
