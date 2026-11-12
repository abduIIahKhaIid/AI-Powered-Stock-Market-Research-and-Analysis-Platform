"""Sends jobs to Celery; a class so the API and the agent can share it and tests can replace it."""

from __future__ import annotations

from .registry import JobKind
from .store import Job


class Queue:
    def enqueue(self, job: Job, kind: JobKind) -> None:
        from ..worker import enqueue

        enqueue(job, kind)

    def revoke(self, job_id: str) -> None:
        from ..worker import revoke

        revoke(job_id)


def get_queue() -> Queue:
    return Queue()
