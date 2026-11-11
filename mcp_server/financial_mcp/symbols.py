"""NASDAQ symbol directory.

Loads Nasdaq Trader's `nasdaqlisted.txt` (all Nasdaq-listed securities, updated during each
trading day), caches it on disk for a day, and answers "is this symbol NASDAQ-listed?" and
"which symbol is this company?". This is what keeps the platform NASDAQ-only.
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
SOURCE_LABEL = "Nasdaq Trader symbol directory (nasdaqlisted.txt)"
EASTERN = ZoneInfo("America/New_York")

MARKET_TIERS = {
    "Q": "Nasdaq Global Select Market",
    "G": "Nasdaq Global Market",
    "S": "Nasdaq Capital Market",
}
FINANCIAL_STATUS = {
    "N": "Normal",
    "D": "Deficient",
    "E": "Delinquent",
    "Q": "Bankrupt",
    "G": "Deficient and Bankrupt",
    "H": "Deficient and Delinquent",
    "J": "Delinquent and Bankrupt",
    "K": "Deficient, Delinquent and Bankrupt",
}

_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class DirectoryUnavailableError(RuntimeError):
    """The symbol directory could not be downloaded and no cached copy exists."""


class NotNasdaqListedError(ValueError):
    """The symbol is not a NASDAQ-listed security."""


@dataclass(frozen=True)
class Listing:
    symbol: str
    name: str
    security_type: str
    market_tier: str
    financial_status: str
    is_etf: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().lstrip("$")
    if not _SYMBOL_RE.match(cleaned):
        raise NotNasdaqListedError(f"'{symbol}' is not a valid ticker symbol.")
    return cleaned


def _split_security_name(raw: str) -> tuple[str, str]:
    # "Apple Inc. - Common Stock" -> ("Apple Inc.", "Common Stock")
    if " - " in raw:
        name, kind = raw.rsplit(" - ", 1)
        return name.strip(), kind.strip()
    return raw.strip(), ""


def parse_nasdaq_listed(text: str) -> tuple[dict[str, Listing], datetime | None]:
    """Parse the pipe-delimited file. Test issues are skipped."""
    listings: dict[str, Listing] = {}
    created: datetime | None = None
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("Symbol|"):
        raise ValueError("Unexpected nasdaqlisted.txt format: missing header row.")

    header = lines[0].split("|")
    col = {name: i for i, name in enumerate(header)}
    for line in lines[1:]:
        if line.startswith("File Creation Time:"):
            stamp = line.split(":", 1)[1].split("|", 1)[0].strip()
            try:
                created = datetime.strptime(stamp, "%m%d%Y%H:%M").replace(tzinfo=EASTERN)
            except ValueError:
                created = None
            continue
        parts = line.split("|")
        if len(parts) < len(header) or parts[col["Test Issue"]] == "Y":
            continue
        name, kind = _split_security_name(parts[col["Security Name"]])
        symbol = parts[col["Symbol"]].strip().upper()
        listings[symbol] = Listing(
            symbol=symbol,
            name=name,
            security_type=kind,
            market_tier=MARKET_TIERS.get(parts[col["Market Category"]], "Unknown"),
            financial_status=FINANCIAL_STATUS.get(parts[col["Financial Status"]], "Unknown"),
            is_etf=parts[col["ETF"]] == "Y",
        )
    return listings, created


def _download(url: str) -> str:
    response = httpx.get(
        url,
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": "stock-research-platform/0.1 (educational project)"},
    )
    response.raise_for_status()
    return response.text


class NasdaqDirectory:
    """In-memory + on-disk cached view of all NASDAQ-listed securities."""

    def __init__(
        self,
        cache_dir: Path,
        url: str = NASDAQ_LISTED_URL,
        max_age_seconds: float = 24 * 3600,
        fetcher: Callable[[str], str] = _download,
    ) -> None:
        self.cache_file = Path(cache_dir) / "nasdaqlisted.txt"
        self.url = url
        self.max_age_seconds = max_age_seconds
        self._fetch = fetcher
        self._listings: dict[str, Listing] = {}
        self._created: datetime | None = None
        self._loaded_at: float = 0.0

    # ----- loading -----
    def _cache_age(self) -> float | None:
        if not self.cache_file.exists():
            return None
        return time.time() - self.cache_file.stat().st_mtime

    def load(self, force: bool = False) -> None:
        fresh_in_memory = time.time() - self._loaded_at < self.max_age_seconds
        if self._listings and fresh_in_memory and not force:
            return

        age = self._cache_age()
        if age is not None and age < self.max_age_seconds and not force:
            self._apply(self.cache_file.read_text(encoding="utf-8"))
            return

        try:
            text = self._fetch(self.url)
            self._apply(text)  # validate before caching
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - fall back to any cached copy
            if age is None:
                raise DirectoryUnavailableError(
                    f"Could not download the NASDAQ symbol directory: {exc}"
                ) from exc
            log.warning("Using stale NASDAQ directory cache (%.0f s old): %s", age, exc)
            self._apply(self.cache_file.read_text(encoding="utf-8"))

    def _apply(self, text: str) -> None:
        self._listings, self._created = parse_nasdaq_listed(text)
        self._loaded_at = time.time()

    # ----- queries -----
    @property
    def as_of(self) -> datetime | None:
        return self._created

    def get(self, symbol: str) -> Listing | None:
        self.load()
        return self._listings.get(normalize_symbol(symbol))

    def require(self, symbol: str) -> Listing:
        listing = self.get(symbol)
        if listing is None:
            raise NotNasdaqListedError(
                f"'{symbol.strip().upper()}' is not listed on NASDAQ. "
                "This assistant only covers NASDAQ-listed securities."
            )
        return listing

    def search(self, query: str, limit: int = 10) -> list[Listing]:
        """Exact symbol first, then symbol prefix, then company-name matches."""
        self.load()
        q = query.strip()
        if not q:
            return []
        q_upper = q.upper().lstrip("$")
        q_lower = q.lower()
        ranked: list[tuple[int, str, Listing]] = []
        for symbol, listing in self._listings.items():
            name_lower = listing.name.lower()
            if symbol == q_upper:
                rank = 0
            elif symbol.startswith(q_upper):
                rank = 1
            elif name_lower.startswith(q_lower):
                rank = 2
            elif q_lower in name_lower:
                rank = 3
            else:
                continue
            # Prefer common stock over warrants/units/ETFs at the same rank.
            tiebreak = 0 if "common" in listing.security_type.lower() else 1
            ranked.append((rank * 2 + tiebreak, symbol, listing))
        ranked.sort(key=lambda item: (item[0], len(item[1]), item[1]))
        return [listing for _, _, listing in ranked[: max(1, min(limit, 25))]]
