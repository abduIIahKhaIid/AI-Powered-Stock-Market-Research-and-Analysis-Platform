"""Dependency checks used by the /health endpoint.

Each check returns "ok" or a short "error: <reason>" string and never raises,
so one broken dependency cannot take the health endpoint down.
"""

import asyncio

import httpx
import psycopg
import redis.asyncio as aioredis

from stock_api.config import Settings


async def check_postgres(url: str, timeout: float) -> str:
    try:
        conn = await asyncio.wait_for(
            psycopg.AsyncConnection.connect(url, connect_timeout=max(1, int(timeout))),
            timeout=timeout,
        )
        async with conn:
            await conn.execute("SELECT 1")
        return "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure as a status string
        return f"error: {type(exc).__name__}"


async def check_redis(url: str, timeout: float) -> str:
    client = aioredis.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        await asyncio.wait_for(client.ping(), timeout=timeout)
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"
    finally:
        await client.aclose()


async def check_mcp_server(url: str, timeout: float) -> str:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
        return "ok" if response.status_code == 200 else f"error: HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


async def collect_service_status(settings: Settings) -> dict[str, str]:
    timeout = settings.health_check_timeout
    postgres, redis_status, mcp = await asyncio.gather(
        check_postgres(settings.database_url, timeout),
        check_redis(settings.redis_url, timeout),
        check_mcp_server(settings.mcp_health_url, timeout),
    )
    return {"api": "ok", "postgres": postgres, "redis": redis_status, "mcp_server": mcp}
