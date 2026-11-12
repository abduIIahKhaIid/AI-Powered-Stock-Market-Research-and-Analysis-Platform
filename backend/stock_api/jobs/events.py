"""Live job progress (SCRUM-33, SCRUM-78).

Every change to a job is published to the Redis pub/sub channel ``job:{id}``. The API
subscribes to that channel and relays each message to the browser as a ``job_progress``
server-sent event, so progress shows up within a second of the worker reporting it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol

from .store import Job, JobStore

logger = logging.getLogger("stock_api.jobs")

Publish = Callable[[Job], None]


def channel(job_id: str) -> str:
    return f"job:{job_id}"


def progress_payload(job: Job) -> dict[str, Any]:
    """What the browser needs to draw the progress bar."""
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "stage": job.stage,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "retry_at": job.retry_at.isoformat() if job.retry_at else None,
        "conversation_id": job.conversation_id,
    }


class PublishingJobStore:
    """A JobStore that publishes every change it makes."""

    def __init__(self, inner: JobStore, publish: Publish) -> None:
        self.inner = inner
        self.publish = publish

    def create(
        self,
        kind: str,
        params: dict[str, Any],
        conversation_id: str | None = None,
        max_attempts: int = 3,
        idempotency_key: str | None = None,
    ) -> Job:
        return self.inner.create(kind, params, conversation_id, max_attempts, idempotency_key)

    def get(self, job_id: str) -> Job:
        return self.inner.get(job_id)

    def find_by_key(self, idempotency_key: str) -> Job | None:
        return self.inner.find_by_key(idempotency_key)

    def update(self, job_id: str, **changes: Any) -> Job:
        job = self.inner.update(job_id, **changes)
        try:
            self.publish(job)
        except Exception as exc:  # noqa: BLE001 - progress is best effort; the row is the truth
            logger.warning("could not publish progress for job %s: %s", job_id, exc)
        return job

    def list(
        self, conversation_id: str | None = None, status: str | None = None, limit: int = 50
    ) -> list[Job]:
        return self.inner.list(conversation_id, status, limit)


class RedisPublisher:
    def __init__(self, redis_url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, socket_timeout=2)

    def __call__(self, job: Job) -> None:
        self._client.publish(channel(job.id), json.dumps(progress_payload(job)))


class Subscription(Protocol):
    async def next(self, timeout: float) -> dict[str, Any] | None:
        """The next progress message, or None when nothing arrived within `timeout`."""
        ...


EventSource = Callable[[str], AbstractAsyncContextManager[Subscription]]


class _RedisSubscription:
    def __init__(self, pubsub: Any) -> None:
        self._pubsub = pubsub

    async def next(self, timeout: float) -> dict[str, Any] | None:
        message = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if message is None:
            return None
        data: dict[str, Any] = json.loads(message["data"])
        return data


class RedisEventSource:
    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url

    @asynccontextmanager
    async def __call__(self, job_id: str) -> AsyncIterator[Subscription]:
        from redis import asyncio as aioredis

        client = aioredis.Redis.from_url(self.redis_url)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel(job_id))
        try:
            yield _RedisSubscription(pubsub)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe()
                await pubsub.aclose()
            await client.aclose()


class _QueueSubscription:
    def __init__(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._queue = queue

    async def next(self, timeout: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        except TimeoutError:
            return None


class MemoryEvents:
    """In-process publisher and event source, for tests and running without Redis."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
        self._lock = threading.Lock()

    def publish(self, job: Job) -> None:
        payload = progress_payload(job)
        with self._lock:
            targets = list(self._subscribers.get(job.id, []))
        for loop, queue in targets:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

    @asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncIterator[Subscription]:
        entry = (asyncio.get_running_loop(), asyncio.Queue[dict[str, Any]]())
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(entry)
        try:
            yield _QueueSubscription(entry[1])
        finally:
            with self._lock:
                self._subscribers[job_id].remove(entry)
