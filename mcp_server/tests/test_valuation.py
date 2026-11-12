from pathlib import Path
from typing import Any

import pytest
from conftest import FakePrices
from mcp.server.mcpserver.exceptions import ToolError

from financial_mcp.sec import RateLimiter, SecClient
from financial_mcp.server import mcp
from financial_mcp.services import Services, set_services

UA = "Abdullah Khalid stock.research.demo@gmail.com"
TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "2": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}


def duration(
    end: str, start: str, val: float, accn: str, form: str = "10-K", filed: str = "2024-11-01"
) -> dict[str, Any]:
    return {
        "end": end,
        "start": start,
        "val": val,
        "form": form,
        "fp": "FY" if form == "10-K" else "Q1",
        "filed": filed,
        "accn": accn,
    }


def instant(end: str, val: float, accn: str) -> dict[str, Any]:
    return {"end": end, "val": val, "form": "10-K", "fp": "FY", "filed": "2024-11-01", "accn": accn}


A24, A23 = "0000320193-24-000123", "0000320193-23-000106"
FY24 = ("2024-09-28", "2023-10-01")
FY23 = ("2023-09-30", "2022-10-02")


def usd(*facts: dict[str, Any]) -> dict[str, Any]:
    return {"units": {"USD": list(facts)}}


APPLE = {
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        {
                            "end": "2024-10-18",
                            "val": 15_000_000_000,
                            "form": "10-K",
                            "filed": "2024-11-01",
                            "accn": A24,
                        },
                    ]
                }
            }
        },
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": usd(
                duration(*FY24, 400e9, A24),
                duration(*FY23, 380e9, A23, filed="2023-11-03"),
                duration(
                    "2024-12-28", "2024-09-29", 120e9, "0000320193-25-000008", "10-Q", "2025-01-31"
                ),
            ),
            "CostOfGoodsAndServicesSold": usd(duration(*FY24, 220e9, A24)),
            "OperatingIncomeLoss": usd(duration(*FY24, 120e9, A24)),
            "NetIncomeLoss": usd(duration(*FY24, 100e9, A24)),
            "EarningsPerShareDiluted": {
                "units": {
                    "USD/shares": [
                        duration(*FY24, 6.5, A24),
                        duration(*FY23, 6.0, A23, filed="2023-11-03"),
                        duration(
                            "2024-12-28",
                            "2024-09-29",
                            2.4,
                            "0000320193-25-000008",
                            "10-Q",
                            "2025-01-31",
                        ),
                    ]
                }
            },
            "DepreciationDepletionAndAmortization": usd(duration(*FY24, 12e9, A24)),
            "CashAndCashEquivalentsAtCarryingValue": usd(instant("2024-09-28", 30e9, A24)),
            "LongTermDebtNoncurrent": usd(instant("2024-09-28", 90e9, A24)),
            "LongTermDebtCurrent": usd(instant("2024-09-28", 10e9, A24)),
        },
    }
}
N24 = "0001045810-24-000029"
NVIDIA = {
    "facts": {
        "dei": {
            "EntityCommonStockSharesOutstanding": {
                "units": {
                    "shares": [
                        {
                            "end": "2024-03-01",
                            "val": 2_400_000_000,
                            "form": "10-K",
                            "filed": "2024-02-21",
                            "accn": N24,
                        },
                    ]
                }
            }
        },
        "us-gaap": {
            "Revenues": usd(duration("2024-01-28", "2023-01-30", 60e9, N24)),
            "NetIncomeLoss": usd(duration("2024-01-28", "2023-01-30", -1.2e9, N24)),
            "EarningsPerShareDiluted": {
                "units": {"USD/shares": [duration("2024-01-28", "2023-01-30", -0.5, N24)]}
            },
            "CashAndCashEquivalentsAtCarryingValue": usd(instant("2024-01-28", 7e9, N24)),
            "NetCashProvidedByUsedInOperatingActivities": usd(
                duration("2024-01-28", "2023-01-30", 28e9, N24)
            ),
        },
    }
}


def fetch(url: str, headers: dict[str, str]) -> Any:
    if url.endswith("company_tickers.json"):
        return TICKERS
    if "CIK0000320193" in url:
        return APPLE
    if "CIK0001045810" in url:
        return NVIDIA
    raise RuntimeError("offline")


class PricesWithCalendar(FakePrices):
    def next_earnings_date(self, symbol: str) -> str | None:
        return "2026-01-29" if symbol == "AAPL" else None


@pytest.fixture
def services(directory: Any, tmp_path: Path) -> Any:
    sec = SecClient(UA, tmp_path, fetcher=fetch, limiter=RateLimiter(interval=0.0))
    set_services(Services(directory=directory, prices=PricesWithCalendar(), sec=sec))
    yield
    set_services(None)


async def call(name: str, arguments: dict[str, Any]) -> Any:
    result = await mcp.call_tool(name, arguments)
    return getattr(result, "structured_content", None)


async def test_valuation_metrics_with_formulas_and_inputs(services: None) -> None:
    body = await call("get_valuation_metrics", {"symbol": "AAPL"})
    data = body["data"]
    values = {key: metric["value"] for key, metric in data["metrics"].items()}
    assert values == {
        "price": 107.1,
        "market_cap": 1_606_500_000_000,
        "pe": 16.48,  # 107.1 / 6.5
        "ps": 4.02,  # 1.6065e12 / 400e9
        "ev_ebitda": 12.7,  # (1.6065e12 + 90e9 + 10e9 - 30e9) / (120e9 + 12e9)
        "gross_margin": 45.0,  # (400e9 - 220e9) / 400e9, gross profit derived from cost
        "operating_margin": 30.0,
        "net_margin": 25.0,
        "revenue_growth": 5.26,  # 400 / 380 - 1
        "eps_growth": 8.33,  # 6.5 / 6.0 - 1
    }
    assert data["metrics"]["pe"]["formula"].startswith("price / diluted EPS")
    assert data["inputs"]["eps_diluted"]["link"].endswith("/000032019324000123/")
    assert data["inputs"]["shares_outstanding"]["value"] == 15_000_000_000
    assert data["fiscal_year_end"] == "2024-09-28"
    assert body["as_of"] == "2026-11-11"


async def test_negative_eps_has_no_pe_and_says_why(services: None) -> None:
    data = (await call("get_valuation_metrics", {"symbol": "NVDA"}))["data"]
    assert data["metrics"]["pe"]["value"] is None
    assert data["metrics"]["ev_ebitda"]["value"] is None
    assert any("not meaningful" in note for note in data["notes"])
    assert any("EBITDA" in note for note in data["notes"])


async def test_earnings_history_and_next_date(services: None) -> None:
    data = (await call("get_earnings", {"symbol": "AAPL"}))["data"]
    assert [row["eps_diluted"] for row in data["annual"]] == [6.5, 6.0]
    assert data["quarterly"][0] == {
        "period_end": "2024-12-28",
        "eps_diluted": 2.4,
        "eps_basic": None,
        "net_income": None,
        "form": "10-Q",
        "filed": "2025-01-31",
        "link": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000008/",
    }
    assert data["next_earnings_date"] == "2026-01-29"
    nvda = (await call("get_earnings", {"symbol": "NVDA"}))["data"]
    assert nvda["next_earnings_date"] is None and "No upcoming" in nvda["note"]


async def test_compare_stocks_gives_a_source_per_cell(services: None) -> None:
    body = await call(
        "compare_stocks", {"symbols": ["aapl", "NVDA", "AAPL"], "metrics": ["pe", "net_margin"]}
    )
    table = body["data"]
    assert table["symbols"] == ["AAPL", "NVDA"]
    pe, margin = table["rows"]
    assert pe["metric"] == "pe" and pe["unit"] == "x"
    assert pe["cells"]["AAPL"]["value"] == 16.48
    assert pe["cells"]["NVDA"]["value"] is None
    assert "fiscal year ending 2024-09-28; price 2026-11-11" in pe["cells"]["AAPL"]["source"]
    assert margin["cells"]["NVDA"]["value"] == -2.0
    assert margin["cells"]["AAPL"]["link"].startswith("https://www.sec.gov/Archives/")


async def test_compare_reports_a_failing_symbol_in_its_cells(services: None) -> None:
    table = (await call("compare_stocks", {"symbols": ["AAPL", "MSFT"], "metrics": ["pe"]}))["data"]
    assert "MSFT" in table["rows"][0]["cells"]["MSFT"]["error"]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"symbols": ["AAPL"]}, "at least two"),
        ({"symbols": ["AAPL", "NVDA", "MSFT", "AMZN", "GOOGL", "META"]}, "at most 5"),
        ({"symbols": ["AAPL", "NVDA"], "metrics": ["beta"]}, "Unknown metrics"),
        ({"symbols": ["AAPL", "IBM"]}, "not listed on NASDAQ"),
    ],
)
async def test_compare_validation(services: None, arguments: dict[str, Any], message: str) -> None:
    with pytest.raises(ToolError, match=message):
        await mcp.call_tool("compare_stocks", arguments)
