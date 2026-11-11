"""Shared dependencies for the tools (symbol directory and price provider).

Created lazily from environment variables; tests swap them with `set_services`.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from financial_mcp.market_data import PriceProvider, YFinanceProvider
from financial_mcp.symbols import NASDAQ_LISTED_URL, NasdaqDirectory


@dataclass
class Services:
    directory: NasdaqDirectory
    prices: PriceProvider


_services: Services | None = None


def default_cache_dir() -> Path:
    return Path(os.getenv("MCP_CACHE_DIR", Path.home() / ".cache" / "financial_mcp"))


def build_default_services() -> Services:
    return Services(
        directory=NasdaqDirectory(
            cache_dir=default_cache_dir(),
            url=os.getenv("NASDAQ_DIRECTORY_URL", NASDAQ_LISTED_URL),
        ),
        prices=YFinanceProvider(),
    )


def get_services() -> Services:
    global _services
    if _services is None:
        _services = build_default_services()
    return _services


def set_services(services: Services | None) -> None:
    global _services
    _services = services
