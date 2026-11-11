"""Financial Analysis MCP server.

Exposes market-data and analysis tools to the agent harness over MCP (streamable HTTP).
This first version only has a `ping` tool and a /health route; the price tools are
added in SCRUM-20.

Run locally:  python -m financial_mcp.server   (listens on MCP_HOST:MCP_PORT, path /mcp)
"""

import os
from datetime import UTC, datetime
from typing import Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

SERVER_NAME = "financial-analysis"
SERVER_VERSION = "0.1.0"

mcp = MCPServer(
    name=SERVER_NAME,
    version=SERVER_VERSION,
    instructions=(
        "Market data and analysis tools for NASDAQ-listed stocks. "
        "Every tool returns {data, source, as_of, units}; quote numbers only from these results."
    ),
)


def envelope(data: Any, source: str, units: str | None = None) -> dict[str, Any]:
    """Standard result shape shared by every tool, so answers can always cite a source."""
    return {
        "data": data,
        "source": source,
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "units": units,
    }


@mcp.tool(description="Check that the Financial Analysis MCP server is reachable.")
def ping() -> dict[str, Any]:
    return envelope("pong", source=SERVER_NAME)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "server": SERVER_NAME, "version": SERVER_VERSION})


def _allowed_hosts() -> list[str]:
    # Host headers accepted by the MCP endpoint (DNS-rebinding protection).
    # "mcp:8100" is the Docker Compose service name used by the API container.
    default = "localhost:*,127.0.0.1:*,mcp:*"
    return [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", default).split(",") if h.strip()]


def create_app() -> Starlette:
    return mcp.streamable_http_app(
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_allowed_hosts(),
            allowed_origins=[],
        ),
    )


def main() -> None:
    uvicorn.run(
        create_app(),
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8100")),
    )


if __name__ == "__main__":
    main()
