"""GET /prices: candles for the chart's own period switcher (SCRUM-36)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from .agent.toolbox import MCPToolbox, Toolbox
from .chart_spec import chart_from_tool
from .config import get_settings

logger = logging.getLogger("stock_api.charts")

router = APIRouter(tags=["charts"])

Period = Literal["5d", "1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y", "10y", "max"]
Interval = Literal["5m", "15m", "30m", "1h", "1d", "1wk", "1mo"]


ToolboxFactory = Callable[[], AbstractAsyncContextManager[Toolbox]]


def toolbox_dependency() -> ToolboxFactory:
    settings = get_settings()
    return lambda: MCPToolbox.connect(settings.mcp_server_url, timeout=settings.mcp_call_timeout)


@router.get("/prices/{symbol}")
async def prices(
    symbol: Annotated[str, Path(pattern=r"^[A-Za-z][A-Za-z0-9.\-]{0,9}$")],
    toolbox_factory: Annotated[ToolboxFactory, Depends(toolbox_dependency)],
    period: Annotated[Period, Query()] = "6mo",
    interval: Annotated[Interval, Query()] = "1d",
) -> dict[str, Any]:
    """Candles for a NASDAQ symbol, in the same chart spec the chat stream sends."""
    arguments = {"symbol": symbol.upper(), "period": period, "interval": interval}
    try:
        async with toolbox_factory() as toolbox:
            outcome = await toolbox.call("get_price_history", arguments)
    except Exception as exc:  # noqa: BLE001 - MCP connection and transport errors
        logger.warning("prices: market data service unreachable: %r", exc)
        raise HTTPException(
            status_code=502, detail="The market data service could not be reached."
        ) from exc

    if not outcome.ok:
        message = outcome.error or "Price data is not available."
        lowered = message.lower()
        status = 404 if ("not listed" in lowered or "no price data" in lowered) else 400
        raise HTTPException(status_code=status, detail=message)
    spec = chart_from_tool("get_price_history", outcome.payload)
    if spec is None:
        raise HTTPException(status_code=404, detail="No price data returned.")
    return spec
