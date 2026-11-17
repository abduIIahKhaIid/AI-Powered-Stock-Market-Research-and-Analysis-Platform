"""Redis TTL cache for tool results (SCRUM-23, SCRUM-58).

Quotes live 60 s, intraday candles 5 minutes and daily or longer candles 12 hours. Every
cached tool call logs a hit or a miss. If Redis is down the tools still work, uncached.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

logger = logging.getLogger("financial_mcp.cache")

QUOTE_TTL = 60
INTRADAY_TTL = 5 * 60
DAILY_TTL = 12 * 3600
INTRADAY_INTERVALS = frozenset({"5m", "15m", "30m", "1h"})
PREFIX = "mcp"

F = TypeVar("F", bound=Callable[..., Any])


class ToolCache(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl: int) -> None: ...

    def delete_matching(self, pattern: str) -> int: ...


class MemoryCache:
    """In-process cache for tests and for running without Redis."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.clock = clock
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item is None or item[0] <= self.clock():
                self._items.pop(key, None)
                return None
            return item[1]

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            self._items[key] = (self.clock() + ttl, value)
            self.ttls[key] = ttl

    def delete_matching(self, pattern: str) -> int:
        import fnmatch

        with self._lock:
            keys = [key for key in self._items if fnmatch.fnmatchcase(key, pattern)]
            for key in keys:
                del self._items[key]
        return len(keys)


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)

    def get(self, key: str) -> Any | None:
        raw = self._client.get(key)
        return None if raw is None else json.loads(raw)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._client.set(key, json.dumps(value, default=str), ex=ttl)

    def delete_matching(self, pattern: str) -> int:
        keys = list(self._client.scan_iter(match=pattern, count=500))
        return int(self._client.delete(*keys)) if keys else 0


def price_ttl(arguments: dict[str, Any]) -> int:
    return INTRADAY_TTL if arguments.get("interval") in INTRADAY_INTERVALS else DAILY_TTL


def cache_key(tool: str, arguments: dict[str, Any]) -> str:
    symbol = str(arguments.get("symbol", "")).upper()
    digest = hashlib.sha1(json.dumps(arguments, sort_keys=True, default=str).encode()).hexdigest()
    return f"{PREFIX}:{tool}:{symbol}:{digest[:16]}"


def cached_tool(
    ttl: int | Callable[[dict[str, Any]], int], get_cache: Callable[[], ToolCache | None]
) -> Callable[[F], F]:
    """Cache a tool's result in Redis, keyed by the tool name and its arguments."""

    def decorate(fn: F) -> F:
        import inspect

        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            cache = get_cache()
            if cache is None:
                return fn(*args, **kwargs)
            key = cache_key(fn.__name__, arguments)
            try:
                hit = cache.get(key)
            except Exception as exc:  # noqa: BLE001 - a cache outage must not break the tool
                logger.warning("cache unavailable tool=%s: %s", fn.__name__, exc)
                return fn(*args, **kwargs)
            if hit is not None:
                logger.info("cache hit tool=%s symbol=%s", fn.__name__, arguments.get("symbol"))
                return hit
            logger.info("cache miss tool=%s symbol=%s", fn.__name__, arguments.get("symbol"))
            result = fn(*args, **kwargs)
            seconds = ttl(arguments) if callable(ttl) else ttl
            try:
                cache.set(key, result, seconds)
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache write failed tool=%s: %s", fn.__name__, exc)
            return result

        return wrapper  # type: ignore[return-value]

    return decorate


def clear_symbol(cache: ToolCache, symbol: str) -> int:
    """Drop every cached tool result for one symbol."""
    return cache.delete_matching(f"{PREFIX}:*:{symbol.upper()}:*")
