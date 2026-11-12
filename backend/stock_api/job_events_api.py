"""Live job progress as server-sent events (SCRUM-33, SCRUM-78).

GET /jobs/{id}/events sends the job's current state, then one ``job_progress`` event for
every change the worker publishes on ``job:{id}``, and a final ``job_done`` event with the
summary to post in the chat. If a message is missed, the stream re-reads the job row
every few seconds, so it never waits on a job that already finished.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import StreamingResponse

from .jobs import JobKind, JobStore, ResultStore, get_job_store, get_registry, get_result_store
from .jobs.events import EventSource, progress_payload
from .jobs.reporting import done_payload
from .jobs.store import TERMINAL, Job, JobNotFound

router = APIRouter(tags=["jobs"])

POLL_SECONDS = 5.0


def event_source_dependency() -> EventSource:
    from .jobs import get_event_source

    return get_event_source()


def get_poll_seconds() -> float:
    return POLL_SECONDS


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _state(payload: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(payload.get(k) for k in ("status", "progress", "stage", "attempts", "error"))


async def relay(
    job_id: str,
    store: JobStore,
    registry: dict[str, JobKind],
    results: ResultStore,
    source: EventSource,
    poll_seconds: float,
) -> AsyncIterator[str]:
    # Subscribe before reading the row, so no change can slip in between.
    async with source(job_id) as subscription:
        job: Job = await asyncio.to_thread(store.get, job_id)
        kind = registry.get(job.kind)
        title = kind.title if kind else job.kind
        current = progress_payload(job) | {"title": title}
        yield sse("job_progress", current)
        while current["status"] not in TERMINAL:
            message = await subscription.next(poll_seconds)
            if message is None:
                job = await asyncio.to_thread(store.get, job_id)
                message = progress_payload(job)
                if _state(message) == _state(current):
                    yield ": keep-alive\n\n"
                    continue
            current = message | {"title": title}
            yield sse("job_progress", current)
    job = await asyncio.to_thread(store.get, job_id)
    yield sse("job_done", await asyncio.to_thread(done_payload, job, kind, results))


@router.get("/jobs/{job_id}/events", response_class=StreamingResponse)
async def job_events(
    job_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    store: Annotated[JobStore, Depends(get_job_store)],
    registry: Annotated[dict[str, JobKind], Depends(get_registry)],
    results: Annotated[ResultStore, Depends(get_result_store)],
    source: Annotated[EventSource, Depends(event_source_dependency)],
    poll_seconds: Annotated[float, Depends(get_poll_seconds)],
) -> StreamingResponse:
    try:
        await asyncio.to_thread(store.get, job_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="No such job.") from None
    return StreamingResponse(
        relay(job_id, store, registry, results, source, poll_seconds),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
