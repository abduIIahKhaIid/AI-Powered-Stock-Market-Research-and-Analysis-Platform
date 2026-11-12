"""Financial statements from SEC EDGAR XBRL data (SCRUM-21).

- Ticker to CIK from https://www.sec.gov/files/company_tickers.json (SCRUM-55)
- Company facts from https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json (SCRUM-56)
- Every request sends a descriptive User-Agent with a contact email and the client stays
  under the SEC's 10 requests per second (SCRUM-57). Responses are cached on disk for a day.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import httpx

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/"
SOURCE_LABEL = "SEC EDGAR company facts (XBRL)"

# The SEC allows 10 requests per second; stay a little below.
MIN_INTERVAL_SECONDS = 0.12
CACHE_SECONDS = 24 * 3600

Fetcher = Callable[[str, dict[str, str]], Any]


class SecError(RuntimeError):
    """SEC data could not be fetched or does not cover the request."""


class SecConfigError(SecError):
    """SEC_USER_AGENT is missing or still the placeholder."""


def validate_user_agent(user_agent: str) -> str:
    agent = (user_agent or "").strip().strip('"')
    if "@" not in agent or "example.com" in agent or len(agent) < 8:
        raise SecConfigError(
            "SEC_USER_AGENT is not set. The SEC requires a descriptive User-Agent with a "
            'contact email, e.g. SEC_USER_AGENT="Your Name your.name@gmail.com" in .env.'
        )
    return agent


def _http_fetch(url: str, headers: dict[str, str]) -> Any:
    response = httpx.get(url, headers=headers, timeout=20.0, follow_redirects=True)
    response.raise_for_status()
    return response.json()


class RateLimiter:
    """Spaces calls at least `interval` seconds apart, across threads."""

    def __init__(
        self,
        interval: float = MIN_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._next > now:
                self._sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


class SecClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Path,
        *,
        fetcher: Fetcher = _http_fetch,
        limiter: RateLimiter | None = None,
        max_age_seconds: int = CACHE_SECONDS,
    ) -> None:
        self.user_agent = user_agent
        self.cache_dir = Path(cache_dir) / "sec"
        self._fetch = fetcher
        self._limiter = limiter or RateLimiter()
        self._max_age = max_age_seconds
        self._tickers: dict[str, tuple[int, str]] | None = None

    def _get_json(self, url: str, cache_name: str) -> Any:
        path = self.cache_dir / cache_name
        if path.exists() and time.time() - path.stat().st_mtime < self._max_age:
            return json.loads(path.read_text(encoding="utf-8"))
        headers = {
            "User-Agent": validate_user_agent(self.user_agent),
            "Accept-Encoding": "gzip, deflate",
        }
        self._limiter.wait()
        try:
            data = self._fetch(url, headers)
        except Exception as exc:  # noqa: BLE001 - network, HTTP and JSON errors alike
            if path.exists():  # serve stale data rather than nothing
                return json.loads(path.read_text(encoding="utf-8"))
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
                raise SecError("The SEC has no XBRL financial data for this company.") from exc
            raise SecError(f"Could not reach SEC EDGAR: {type(exc).__name__}.") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return data

    def lookup(self, symbol: str) -> tuple[int, str]:
        """CIK and company name for a ticker."""
        if self._tickers is None:
            raw = self._get_json(TICKERS_URL, "company_tickers.json")
            rows = raw.values() if isinstance(raw, dict) else raw
            self._tickers = {
                str(row["ticker"]).upper(): (int(row["cik_str"]), str(row["title"])) for row in rows
            }
        key = symbol.upper().replace(".", "-")
        found = self._tickers.get(key) or self._tickers.get(symbol.upper())
        if found is None:
            raise SecError(f"{symbol} has no SEC filer record (it may file outside EDGAR).")
        return found

    def company_facts(self, cik: int) -> dict[str, Any]:
        return self._get_json(FACTS_URL.format(cik=cik), f"companyfacts_{cik}.json")


# --- statements ----------------------------------------------------------------------


@dataclass(frozen=True)
class LineItem:
    key: str
    label: str
    tags: tuple[str, ...]
    unit: str = "USD"
    instant: bool = False


STATEMENTS: dict[str, list[LineItem]] = {
    "income": [
        LineItem(
            "revenue",
            "Revenue",
            (
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
            ),
        ),
        LineItem(
            "cost_of_revenue",
            "Cost of revenue",
            ("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"),
        ),
        LineItem("gross_profit", "Gross profit", ("GrossProfit",)),
        LineItem(
            "research_and_development",
            "Research and development",
            ("ResearchAndDevelopmentExpense",),
        ),
        LineItem("operating_expenses", "Operating expenses", ("OperatingExpenses",)),
        LineItem("operating_income", "Operating income", ("OperatingIncomeLoss",)),
        LineItem("net_income", "Net income", ("NetIncomeLoss", "ProfitLoss")),
        LineItem("eps_basic", "EPS, basic", ("EarningsPerShareBasic",), unit="USD/shares"),
        LineItem("eps_diluted", "EPS, diluted", ("EarningsPerShareDiluted",), unit="USD/shares"),
        LineItem(
            "diluted_shares",
            "Diluted weighted shares",
            ("WeightedAverageNumberOfDilutedSharesOutstanding",),
            unit="shares",
        ),
    ],
    "balance": [
        LineItem(
            "cash",
            "Cash and cash equivalents",
            ("CashAndCashEquivalentsAtCarryingValue",),
            instant=True,
        ),
        LineItem("current_assets", "Current assets", ("AssetsCurrent",), instant=True),
        LineItem("total_assets", "Total assets", ("Assets",), instant=True),
        LineItem(
            "current_liabilities", "Current liabilities", ("LiabilitiesCurrent",), instant=True
        ),
        LineItem(
            "long_term_debt",
            "Long-term debt",
            ("LongTermDebtNoncurrent", "LongTermDebt"),
            instant=True,
        ),
        LineItem(
            "short_term_debt",
            "Short-term debt",
            ("LongTermDebtCurrent", "ShortTermBorrowings", "CommercialPaper"),
            instant=True,
        ),
        LineItem("total_liabilities", "Total liabilities", ("Liabilities",), instant=True),
        LineItem(
            "stockholders_equity",
            "Stockholders' equity",
            (
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            ),
            instant=True,
        ),
    ],
    "cash_flow": [
        LineItem(
            "operating_cash_flow",
            "Operating cash flow",
            ("NetCashProvidedByUsedInOperatingActivities",),
        ),
        LineItem(
            "capital_expenditure",
            "Capital expenditure",
            ("PaymentsToAcquirePropertyPlantAndEquipment",),
        ),
        LineItem(
            "dividends_paid",
            "Dividends paid",
            ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
        ),
        LineItem("share_repurchases", "Share repurchases", ("PaymentsForRepurchaseOfCommonStock",)),
        LineItem(
            "depreciation_amortization",
            "Depreciation and amortization",
            (
                "DepreciationDepletionAndAmortization",
                "DepreciationAndAmortization",
                "DepreciationAmortizationAndAccretionNet",
            ),
        ),
    ],
}


@dataclass(frozen=True)
class Derived:
    key: str
    label: str
    formula: str
    inputs: tuple[str, ...]
    compute: Callable[[dict[str, float]], float]


DERIVED: dict[str, list[Derived]] = {
    "cash_flow": [
        Derived(
            "free_cash_flow",
            "Free cash flow",
            "operating_cash_flow - capital_expenditure",
            ("operating_cash_flow", "capital_expenditure"),
            lambda v: v["operating_cash_flow"] - v["capital_expenditure"],
        )
    ]
}
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}
ANNUAL_DAYS = (340, 380)
QUARTER_DAYS = (80, 100)


def _days(fact: dict[str, Any]) -> int | None:
    if not fact.get("start"):
        return None
    return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days


def _matches(fact: dict[str, Any], item: LineItem, freq: str) -> bool:
    if fact.get("form") not in FORMS or fact.get("val") is None:
        return False
    if item.instant:
        if freq == "annual":
            return str(fact.get("form", "")).startswith("10-K") and fact.get("fp") == "FY"
        return True
    days = _days(fact)
    low, high = ANNUAL_DAYS if freq == "annual" else QUARTER_DAYS
    return days is not None and low <= days <= high


def _item_facts(gaap: dict[str, Any], item: LineItem, freq: str) -> dict[str, dict[str, Any]]:
    """Facts for one line item by period end; earlier tags win, later tags fill gaps."""
    by_end: dict[str, dict[str, Any]] = {}
    for tag in item.tags:
        facts = gaap.get(tag, {}).get("units", {}).get(item.unit, [])
        best: dict[str, dict[str, Any]] = {}
        for fact in facts:
            if not _matches(fact, item, freq):
                continue
            current = best.get(fact["end"])
            # A later filing restates or repeats the value; keep the most recent one.
            if current is None or fact.get("filed", "") > current.get("filed", ""):
                best[fact["end"]] = {**fact, "tag": tag}
        for end, fact in best.items():
            by_end.setdefault(end, fact)
    return by_end


def build_statement(
    facts: dict[str, Any], cik: int, statement: str, freq: str, count: int
) -> dict[str, Any]:
    if statement not in STATEMENTS:
        raise SecError(f"Unknown statement '{statement}'. Use income, balance or cash_flow.")
    if freq not in ("annual", "quarterly"):
        raise SecError("freq must be annual or quarterly.")
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        raise SecError(
            "This company does not report US-GAAP XBRL data (foreign filers using IFRS are "
            "not covered yet)."
        )
    items = STATEMENTS[statement]
    per_item = {item.key: _item_facts(gaap, item, freq) for item in items}
    ends = sorted({end for facts_by_end in per_item.values() for end in facts_by_end}, reverse=True)
    periods: list[dict[str, Any]] = []
    for end in ends[:count]:
        values: dict[str, float] = {}
        tags: dict[str, str] = {}
        anchor: dict[str, Any] | None = None
        for item in items:
            fact = per_item[item.key].get(end)
            if fact is None:
                continue
            values[item.key] = fact["val"]
            tags[item.key] = fact["tag"]
            if anchor is None or fact.get("filed", "") > anchor.get("filed", ""):
                anchor = fact
        for rule in DERIVED.get(statement, []):
            if all(need in values for need in rule.inputs):
                values[rule.key] = rule.compute(values)
        assert anchor is not None
        accession = str(anchor.get("accn", ""))
        periods.append(
            {
                "end": end,
                "start": anchor.get("start"),
                "form": anchor.get("form"),
                "filed": anchor.get("filed"),
                "accession": accession,
                "link": FILING_URL.format(cik=cik, accession=accession.replace("-", "")),
                "values": values,
                "tags": tags,
            }
        )
    if not periods:
        raise SecError(f"No {freq} {statement} data found in the company's XBRL filings.")
    line_items = {item.key: f"{item.label} ({item.unit})" for item in items}
    derived: dict[str, str] = {}
    for rule in DERIVED.get(statement, []):
        line_items[rule.key] = f"{rule.label} (USD)"
        derived[rule.key] = rule.formula
    reported = {key for period in periods for key in period["values"]}
    return {
        "statement": statement,
        "freq": freq,
        "line_items": line_items,
        "derived": derived,
        "missing": [key for key in line_items if key not in reported],
        "periods": periods,
        "url": periods[0]["link"],
        "latest_filed": max(str(p["filed"]) for p in periods),
    }


def shares_outstanding(facts: dict[str, Any], cik: int) -> dict[str, Any] | None:
    """Latest common shares outstanding from the filing cover page (dei)."""
    entries = (
        facts.get("facts", {})
        .get("dei", {})
        .get("EntityCommonStockSharesOutstanding", {})
        .get("units", {})
        .get("shares", [])
    )
    entries = [e for e in entries if e.get("val") and e.get("form") in FORMS]
    if not entries:
        return None
    latest = max(entries, key=lambda e: (e.get("end", ""), e.get("filed", "")))
    accession = str(latest.get("accn", ""))
    return {
        "value": latest["val"],
        "date": latest.get("end"),
        "form": latest.get("form"),
        "link": FILING_URL.format(cik=cik, accession=accession.replace("-", "")),
    }
