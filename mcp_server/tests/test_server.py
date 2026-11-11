import httpx

from financial_mcp.server import create_app, envelope, mcp, ping


def test_envelope_has_standard_keys() -> None:
    result = envelope(123, source="unit-test", units="USD")
    assert set(result) == {"data", "source", "as_of", "units"}
    assert result["units"] == "USD"


def test_ping_tool_returns_envelope() -> None:
    result = ping()
    assert result["data"] == "pong"
    assert result["source"] == "financial-analysis"


async def test_ping_is_registered_as_tool() -> None:
    names = [tool.name for tool in await mcp.list_tools()]
    assert "ping" in names


async def test_health_route() -> None:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8100") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
