"""Job API: create, get, cancel and list background jobs (SCRUM-32, SCRUM-77), plus saved
results, file downloads and the saved analyses list (SCRUM-34)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .jobs import Job, JobKind, JobStore, ResultStore, get_job_store, get_registry, get_result_store
from .jobs.queue import Queue, get_queue
from .jobs.registry import JobInputError
from .jobs.results import ResultFileError, load_result
from .jobs.store import JobNotFound

router = APIRouter(tags=["jobs"])

JobId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]
FileName = Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")]
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._:-]{8,100}$")
]


class JobRequest(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")


Store = Annotated[JobStore, Depends(get_job_store)]
Registry = Annotated[dict[str, JobKind], Depends(get_registry)]
Queued = Annotated[Queue, Depends(get_queue)]
Results = Annotated[ResultStore, Depends(get_result_store)]


def _get(store: JobStore, job_id: str) -> Job:
    try:
        return store.get(job_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="No such job.") from None


@router.post("/jobs", status_code=202)
def create_job(
    body: JobRequest,
    store: Store,
    registry: Registry,
    queue: Queued,
    response: Response,
    idempotency_key: IdempotencyKey = None,
) -> dict[str, Any]:
    """Queue a job. Sending the same Idempotency-Key again returns the first job (200)."""
    kind = registry.get(body.kind)
    if kind is None:
        raise HTTPException(
            status_code=422, detail=f"Unknown job kind. Use one of: {', '.join(sorted(registry))}."
        )
    try:
        params = kind.validate(body.params)
    except JobInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if idempotency_key is not None:
        existing = store.find_by_key(idempotency_key)
        if existing is not None:
            if (existing.kind, existing.params) != (kind.name, params):
                raise HTTPException(
                    status_code=409,
                    detail="This Idempotency-Key was already used for a different job.",
                )
            response.status_code = 200
            return existing.to_dict()
    job = store.create(
        kind.name,
        params,
        body.conversation_id,
        max_attempts=kind.max_attempts,
        idempotency_key=idempotency_key,
    )
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


@router.get("/jobs/{job_id}/result")
def get_result(job_id: JobId, store: Store, results: Results) -> dict[str, Any]:
    """The full result of a finished job, also when it was too large for the job row."""
    job = _get(store, job_id)
    if job.status != "succeeded":
        raise HTTPException(status_code=409, detail=f"The job is {job.status}; no result yet.")
    try:
        result = load_result(job.id, job.result, job.result_path, results)
    except FileNotFoundError:
        raise HTTPException(status_code=410, detail="The saved result file is missing.") from None
    return {"job": job.to_dict(), "result": result}


@router.get("/jobs/{job_id}/files/{name}")
def download_file(job_id: JobId, name: FileName, store: Store, results: Results) -> FileResponse:
    job = _get(store, job_id)
    saved = next((f for f in job.files if f["name"] == name), None)
    if saved is None:
        raise HTTPException(status_code=404, detail="This job has no such file.")
    try:
        path = results.path(job.id, name)
    except ResultFileError:
        raise HTTPException(status_code=404, detail="This job has no such file.") from None
    if not path.is_file():
        raise HTTPException(status_code=410, detail="The saved file is missing.")
    return FileResponse(path, media_type=saved["media_type"], filename=name)


@router.get("/analyses")
def saved_analyses(
    store: Store,
    registry: Registry,
    conversation_id: Annotated[str | None, Query(pattern=r"^[0-9a-f]{32}$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    """Finished analyses, newest first, so results can be reopened after a restart."""
    return [
        {
            "id": job.id,
            "kind": job.kind,
            "title": registry[job.kind].title if job.kind in registry else job.kind,
            "summary": job.summary,
            "conversation_id": job.conversation_id,
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "files": job.files,
        }
        for job in store.list(conversation_id, "succeeded", limit)
    ]
