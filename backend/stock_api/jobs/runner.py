"""Runs one job from start to finish; used by the Celery task and by tests (SCRUM-32)."""

from __future__ import annotations

import logging
from typing import Any

from .registry import JobCancelled, JobContext, JobKind
from .store import Job, JobStore

logger = logging.getLogger("stock_api.jobs")


def _too_long(exc: BaseException) -> bool:
    try:
        from celery.exceptions import SoftTimeLimitExceeded
    except ImportError:  # pragma: no cover
        return False
    return isinstance(exc, SoftTimeLimitExceeded)


def execute(job_id: str, store: JobStore, registry: dict[str, JobKind]) -> Job:
    """Run the job unless it already finished; the job id makes repeated runs harmless."""
    job = store.get(job_id)
    if job.done:
        return job
    if job.cancel_requested:
        return store.update(job_id, status="cancelled", stage="Cancelled before it started")
    kind = registry.get(job.kind)
    if kind is None:
        return store.update(job_id, status="failed", error=f"Unknown job kind '{job.kind}'.")

    job = store.update(
        job_id, status="running", attempts=job.attempts + 1, stage="Starting", error=None
    )
    ctx = JobContext(store, job_id)
    try:
        result: Any = kind.handler(job.params, ctx)
    except JobCancelled:
        return store.update(job_id, status="cancelled", stage="Cancelled")
    except Exception as exc:  # noqa: BLE001 - recorded on the job, not raised to Celery
        if _too_long(exc):
            message = f"Took longer than the {kind.soft_limit} s limit for this job."
        else:
            message = f"{type(exc).__name__}: {exc}"
        logger.warning("job %s (%s) failed: %s", job_id, job.kind, message)
        return store.update(job_id, status="failed", stage="Failed", error=message)
    return store.update(job_id, status="succeeded", progress=100, stage="Done", result=result)
