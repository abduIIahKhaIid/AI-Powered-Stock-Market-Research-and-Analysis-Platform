"""Shared dependencies for the tools (symbol directory, price provider, SEC client).

Created lazily from environment variables; tests swap them with `set_services`.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from financial_mcp.alpha_vantage import (
    AlphaVantageClient,
    AlphaVantagePrices,
    FallbackPrices,
    McpCaller,
)
from financial_mcp.market_data import PriceProvider, YFinanceProvider
from financial_mcp.sec import SecClient
from financial_mcp.symbols import NASDAQ_LISTED_URL, NasdaqDirectory


@dataclass
class Services:
    directory: NasdaqDirectory
    prices: PriceProvider
    sec: SecClient | None = None
    # Alpha Vantage (SCRUM-22): only when ALPHAVANTAGE_API_KEY is set.
    alpha_vantage: AlphaVantageClient | None = None


_services: Services | None = None


def default_cache_dir() -> Path:
    return Path(os.getenv("MCP_CACHE_DIR", Path.home() / ".cache" / "financial_mcp"))


def build_alpha_vantage() -> AlphaVantageClient | None:
    key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    if not key:
        return None
    caller = McpCaller(key, os.getenv("ALPHAVANTAGE_MCP_URL", "https://mcp.alphavantage.co/mcp"))
    return AlphaVantageClient(
        caller,
        default_cache_dir(),
        daily_limit=int(os.getenv("ALPHAVANTAGE_DAILY_LIMIT", "25")),
    )


def build_default_services() -> Services:
    alpha_vantage = build_alpha_vantage()
    prices: PriceProvider = YFinanceProvider()
    if alpha_vantage is not None:
        prices = FallbackPrices(prices, AlphaVantagePrices(alpha_vantage))
    return Services(
        directory=NasdaqDirectory(
            cache_dir=default_cache_dir(),
            url=os.getenv("NASDAQ_DIRECTORY_URL", NASDAQ_LISTED_URL),
        ),
        prices=prices,
        sec=SecClient(os.getenv("SEC_USER_AGENT", ""), default_cache_dir()),
        alpha_vantage=alpha_vantage,
    )


def get_services() -> Services:
    global _services
    if _services is None:
        _services = build_default_services()
    return _services


def set_services(services: Services | None) -> None:
    global _services
    _services = services
