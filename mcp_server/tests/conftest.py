from pathlib import Path

import pytest

from financial_mcp.market_data import Candle, PriceDataError
from financial_mcp.services import Services, set_services
from financial_mcp.symbols import NasdaqDirectory

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_TEXT = (FIXTURES / "nasdaqlisted_sample.txt").read_text(encoding="utf-8")


class FakePrices:
    source = "Fake price source (tests)"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        self.calls.append((symbol, period, interval))
        if symbol == "SMLC":
            raise PriceDataError("No price data returned for SMLC (5d, 1d).")
        return [
            Candle("2026-11-09", 100.0, 103.0, 99.0, 102.0, 1_000_000),
            Candle("2026-11-10", 102.0, 106.0, 101.5, 105.0, 1_200_000),
            Candle("2026-11-11", 105.0, 107.5, 104.0, 107.1, 1_500_000),
        ]


@pytest.fixture
def directory(tmp_path: Path) -> NasdaqDirectory:
    return NasdaqDirectory(cache_dir=tmp_path, fetcher=lambda url: SAMPLE_TEXT)


@pytest.fixture
def fake_prices() -> FakePrices:
    return FakePrices()


@pytest.fixture
def services(directory: NasdaqDirectory, fake_prices: FakePrices):
    svc = Services(directory=directory, prices=fake_prices)
    set_services(svc)
    yield svc
    set_services(None)
