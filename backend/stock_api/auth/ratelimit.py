"""Per-user request limits (SCRUM-40): a fixed one-minute window per user and route group."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("stock_api.ratelimit")

WINDOW_SECONDS = 60


@dataclass(frozen=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class RateLimiter(Protocol):
    def hit(self, bucket: str, subject: str, limit: int) -> Decision: ...


def _window(now: float) -> tuple[int, int]:
    window = int(now // WINDOW_SECONDS)
    retry_after = int((window + 1) * WINDOW_SECONDS - now) + 1
    return window, retry_after


class MemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._counts: dict[tuple[str, str, int], int] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def hit(self, bucket: str, subject: str, limit: int) -> Decision:
        window, retry_after = _window(self._clock())
        with self._lock:
            self._counts = {k: v for k, v in self._counts.items() if k[2] >= window}
            key = (bucket, subject, window)
            self._counts[key] = count = self._counts.get(key, 0) + 1
        return Decision(count <= limit, limit, max(0, limit - count), retry_after)


class RedisRateLimiter:
    """Shared by every API process. If Redis is down, requests are let through (and logged)."""

    def __init__(self, redis_url: str, clock: Callable[[], float] = time.time) -> None:
        import redis

        self._client = redis.Redis.from_url(redis_url, socket_timeout=1, socket_connect_timeout=1)
        self._clock = clock

    def hit(self, bucket: str, subject: str, limit: int) -> Decision:
        window, retry_after = _window(self._clock())
        key = f"ratelimit:{bucket}:{subject}:{window}"
        try:
            pipe = self._client.pipeline()
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS + 5)
            count = int(pipe.execute()[0])
        except Exception as exc:  # noqa: BLE001 - availability over limiting when Redis is down
            logger.warning("rate limit check skipped: %s", exc)
            return Decision(True, limit, limit, 0)
        return Decision(count <= limit, limit, max(0, limit - count), retry_after)
