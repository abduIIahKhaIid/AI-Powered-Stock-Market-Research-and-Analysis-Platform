import httpx
import pytest

from stock_api import health
from stock_api.main import app
from stock_api.worker import ping


@pytest.fixture
def client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_live_is_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_ok_when_all_services_ok(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def all_ok(settings: object) -> dict[str, str]:
        return {"api": "ok", "postgres": "ok", "redis": "ok", "mcp_server": "ok"}

    monkeypatch.setattr(health, "collect_service_status", all_ok)
    response = await client.get("/health")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["services"]["postgres"] == "ok"


async def test_health_degraded_but_200_when_a_service_is_down(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def postgres_down(settings: object) -> dict[str, str]:
        return {
            "api": "ok",
            "postgres": "error: OperationalError",
            "redis": "ok",
            "mcp_server": "ok",
        }

    monkeypatch.setattr(health, "collect_service_status", postgres_down)
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


async def test_real_checks_report_errors_instead_of_raising() -> None:
    # Nothing listens on these ports, so every check must return an error string.
    assert (await health.check_redis("redis://127.0.0.1:1/0", 0.5)).startswith("error")
    assert (await health.check_mcp_server("http://127.0.0.1:1/health", 0.5)).startswith("error")
    assert (await health.check_postgres("postgresql://u:p@127.0.0.1:1/db", 1.0)).startswith("error")


def test_worker_ping_task() -> None:
    assert ping() == "pong"
