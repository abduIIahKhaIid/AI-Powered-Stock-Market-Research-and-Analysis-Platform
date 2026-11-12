"""Job API: create, get, cancel and list background jobs (SCRUM-32, SCRUM-77)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field

from .jobs import Job, JobKind, JobStore, get_job_store, get_registry
from .jobs.registry import JobInputError
from .jobs.store import JobNotFound

router = APIRouter(tags=["jobs"])

JobId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


class JobRequest(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


class Queue:
    """Wraps the Celery calls so tests can replace them."""

    def enqueue(self, job: Job, kind: JobKind) -> None:
        from .worker import enqueue

        enqueue(job, kind)

    def revoke(self, job_id: str) -> None:
        from .worker import revoke

        revoke(job_id)


def get_queue() -> Queue:
    return Queue()


Store = Annotated[JobStore, Depends(get_job_store)]
Registry = Annotated[dict[str, JobKind], Depends(get_registry)]
Queued = Annotated[Queue, Depends(get_queue)]


def _get(store: JobStore, job_id: str) -> Job:
    try:
        return store.get(job_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="No such job.") from None


@router.post("/jobs", status_code=202)
def create_job(body: JobRequest, store: Store, registry: Registry, queue: Queued) -> dict[str, Any]:
    kind = registry.get(body.kind)
    if kind is None:
        raise HTTPException(
            status_code=422, detail=f"Unknown job kind. Use one of: {', '.join(sorted(registry))}."
        )
    try:
        params = kind.validate(body.params)
    except JobInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    job = store.create(kind.name, params, body.conversation_id, max_attempts=kind.max_attempts)
    queue.enqueue(job, kind)
    return job.to_dict()


@router.get("/jobs/{job_id}")
def get_job(job_id: JobId, store: Store) -> dict[str, Any]:
    return _get(store, job_id).to_dict()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: JobId, store: Store, queue: Queued) -> dict[str, Any]:
    job = _get(store, job_id)
    if job.done:
        raise HTTPException(status_code=409, detail=f"The job is already {job.status}.")
    if job.status == "queued":
        job = store.update(job_id, status="cancelled", cancel_requested=True, stage="Cancelled")
    else:
        # A running job stops at its next progress update.
        job = store.update(job_id, cancel_requested=True, stage="Cancelling")
    queue.revoke(job_id)
    return job.to_dict()


@router.get("/jobs")
def list_jobs(
    store: Store,
    conversation_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")] = None,
    status: Annotated[
        str | None, Query(pattern=r"^(queued|running|succeeded|failed|cancelled)$")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return [job.to_dict() for job in store.list(conversation_id, status, limit)]
