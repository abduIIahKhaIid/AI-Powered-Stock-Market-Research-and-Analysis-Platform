from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from financial_mcp.sec import (
    RateLimiter,
    SecClient,
    SecConfigError,
    SecError,
    build_statement,
    validate_user_agent,
)
from financial_mcp.server import mcp
from financial_mcp.services import Services, set_services

UA = "Abdullah Khalid stock.research.demo@gmail.com"
TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
}


def fact(
    end: str,
    val: float,
    form: str,
    filed: str,
    start: str | None = None,
    fp: str = "FY",
    accn: str = "0000320193-24-000123",
) -> dict[str, Any]:
    out = {"end": end, "val": val, "form": form, "filed": filed, "fp": fp, "accn": accn}
    if start:
        out["start"] = start
    return out


FACTS = {
    "cik": 320193,
    "facts": {
        "us-gaap": {
            # Older years use "Revenues", newer ones the ASC 606 tag: both must be found.
            "Revenues": {
                "units": {
                    "USD": [
                        fact(
                            "2021-09-25",
                            365_817_000_000,
                            "10-K",
                            "2021-10-29",
                            "2020-09-27",
                            accn="0000320193-21-000105",
                        ),
                    ]
                }
            },
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        fact(
                            "2022-09-24",
                            394_328_000_000,
                            "10-K",
                            "2022-10-28",
                            "2021-09-26",
                            accn="0000320193-22-000108",
                        ),
                        # Restated as a comparative in the next 10-K: latest wins.
                        fact(
                            "2022-09-24",
                            394_300_000_000,
                            "10-K",
                            "2023-11-03",
                            "2021-09-26",
                            accn="0000320193-23-000106",
                        ),
                        fact(
                            "2023-09-30",
                            383_285_000_000,
                            "10-K",
                            "2023-11-03",
                            "2022-09-25",
                            accn="0000320193-23-000106",
                        ),
                        # A quarter inside a 10-Q must not leak into annual data.
                        fact(
                            "2023-07-01",
                            81_797_000_000,
                            "10-Q",
                            "2023-08-04",
                            "2023-04-02",
                            fp="Q3",
                            accn="0000320193-23-000077",
                        ),
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        fact(
                            "2023-09-30",
                            96_995_000_000,
                            "10-K",
                            "2023-11-03",
                            "2022-09-25",
                            accn="0000320193-23-000106",
                        ),
                        fact(
                            "2023-07-01",
                            19_881_000_000,
                            "10-Q",
                            "2023-08-04",
                            "2023-04-02",
                            fp="Q3",
                            accn="0000320193-23-000077",
                        ),
                    ]
                }
            },
            "EarningsPerShareDiluted": {
                "units": {
                    "USD/shares": [
                        fact(
                            "2023-09-30",
                            6.13,
                            "10-K",
                            "2023-11-03",
                            "2022-09-25",
                            accn="0000320193-23-000106",
                        ),
                    ]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        fact(
                            "2023-09-30",
                            352_583_000_000,
                            "10-K",
                            "2023-11-03",
                            accn="0000320193-23-000106",
                        ),
                        fact(
                            "2023-07-01",
                            335_038_000_000,
                            "10-Q",
                            "2023-08-04",
                            fp="Q3",
                            accn="0000320193-23-000077",
                        ),
                    ]
                }
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {
                    "USD": [
                        fact(
                            "2023-09-30",
                            110_543_000_000,
                            "10-K",
                            "2023-11-03",
                            "2022-09-25",
                            accn="0000320193-23-000106",
                        ),
                    ]
                }
            },
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {
                    "USD": [
                        fact(
                            "2023-09-30",
                            10_959_000_000,
                            "10-K",
                            "2023-11-03",
                            "2022-09-25",
                            accn="0000320193-23-000106",
                        ),
                    ]
                }
            },
        }
    },
}


class FakeSec:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> Any:
        self.requests.append((url, headers))
        if url.endswith("company_tickers.json"):
            return TICKERS
        if "CIK0000320193" in url:
            return FACTS
        request = httpx.Request("GET", url)
        raise httpx.HTTPStatusError(
            "not found", request=request, response=httpx.Response(404, request=request)
        )


@pytest.fixture
def fake_sec() -> FakeSec:
    return FakeSec()


@pytest.fixture
def client(tmp_path: Path, fake_sec: FakeSec) -> SecClient:
    limiter = RateLimiter(interval=0.0)
    return SecClient(UA, tmp_path, fetcher=fake_sec, limiter=limiter)


def test_user_agent_must_have_a_contact_email() -> None:
    assert validate_user_agent(f'"{UA}"') == UA
    for bad in ("", "python-httpx", "Your Name your.email@example.com"):
        with pytest.raises(SecConfigError, match="SEC_USER_AGENT"):
            validate_user_agent(bad)


def test_rate_limiter_spaces_requests() -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(round(seconds, 3))
        now[0] += seconds

    limiter = RateLimiter(interval=0.12, clock=lambda: now[0], sleep=sleep)
    for _ in range(4):
        limiter.wait()
    assert slept == [0.12, 0.12, 0.12]  # at most ~8 requests per second


def test_lookup_maps_ticker_to_cik_and_sends_user_agent(
    client: SecClient, fake_sec: FakeSec
) -> None:
    assert client.lookup("aapl") == (320193, "Apple Inc.")
    assert client.lookup("NVDA") == (1045810, "NVIDIA CORP")
    url, headers = fake_sec.requests[0]
    assert url == "https://www.sec.gov/files/company_tickers.json"
    assert headers["User-Agent"] == UA
    with pytest.raises(SecError, match="no SEC filer record"):
        client.lookup("ZZZZ")


def test_responses_are_cached(client: SecClient, fake_sec: FakeSec) -> None:
    client.company_facts(320193)
    client.company_facts(320193)
    assert sum("companyfacts" in url for url, _ in fake_sec.requests) == 1


def test_missing_company_facts_is_a_clear_error(client: SecClient) -> None:
    with pytest.raises(SecError, match="no XBRL financial data"):
        client.company_facts(1045810)


def test_annual_income_statement_uses_tag_fallbacks_and_latest_filing() -> None:
    data = build_statement(FACTS, 320193, "income", "annual", 5)
    periods = {p["end"]: p for p in data["periods"]}
    assert list(periods) == ["2023-09-30", "2022-09-24", "2021-09-25"]
    assert periods["2021-09-25"]["values"]["revenue"] == 365_817_000_000
    assert periods["2021-09-25"]["tags"]["revenue"] == "Revenues"
    assert periods["2022-09-24"]["values"]["revenue"] == 394_300_000_000  # restated value
    latest = periods["2023-09-30"]
    assert latest["values"] == {
        "revenue": 383_285_000_000,
        "net_income": 96_995_000_000,
        "eps_diluted": 6.13,
    }
    assert latest["form"] == "10-K"
    assert latest["link"] == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/"
    assert data["url"] == latest["link"]
    assert "gross_profit" in data["missing"]


def test_quarterly_and_balance_and_cash_flow() -> None:
    quarterly = build_statement(FACTS, 320193, "income", "quarterly", 4)
    assert [p["end"] for p in quarterly["periods"]] == ["2023-07-01"]
    assert quarterly["periods"][0]["values"]["revenue"] == 81_797_000_000

    balance = build_statement(FACTS, 320193, "balance", "annual", 5)
    assert [p["end"] for p in balance["periods"]] == ["2023-09-30"]
    assert balance["periods"][0]["values"]["total_assets"] == 352_583_000_000

    cash = build_statement(FACTS, 320193, "cash_flow", "annual", 5)
    values = cash["periods"][0]["values"]
    assert values["free_cash_flow"] == 110_543_000_000 - 10_959_000_000
    assert cash["derived"]["free_cash_flow"] == "operating_cash_flow - capital_expenditure"


def test_bad_statement_and_ifrs_filers() -> None:
    with pytest.raises(SecError, match="Unknown statement"):
        build_statement(FACTS, 1, "profit", "annual", 5)
    with pytest.raises(SecError, match="IFRS"):
        build_statement({"facts": {"ifrs-full": {}}}, 1, "income", "annual", 5)


# --- the MCP tool --------------------------------------------------------------------


@pytest.fixture
def sec_services(directory: Any, client: SecClient) -> Any:
    from conftest import FakePrices

    set_services(Services(directory=directory, prices=FakePrices(), sec=client))
    yield
    set_services(None)


async def test_tool_returns_statement_with_filing_links(sec_services: None) -> None:
    result = await mcp.call_tool(
        "get_financial_statements", {"symbol": "AAPL", "statement": "income", "years": 2}
    )
    body: Any = getattr(result, "structured_content", None)
    assert body["source"] == "SEC EDGAR company facts (XBRL)"
    assert body["as_of"] == "2023-11-03"
    data = body["data"]
    assert (data["symbol"], data["cik"], data["freq"]) == ("AAPL", 320193, "annual")
    assert [p["end"] for p in data["periods"]] == ["2023-09-30", "2022-09-24"]
    assert data["url"].startswith("https://www.sec.gov/Archives/edgar/data/320193/")


async def test_tool_errors(sec_services: None) -> None:
    with pytest.raises(ToolError, match="not listed on NASDAQ"):
        await mcp.call_tool("get_financial_statements", {"symbol": "IBM"})
    with pytest.raises(ToolError, match="Unknown statement"):
        await mcp.call_tool("get_financial_statements", {"symbol": "AAPL", "statement": "x"})
