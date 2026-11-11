import os
import time
from pathlib import Path

import pytest
from conftest import SAMPLE_TEXT

from financial_mcp.symbols import (
    DirectoryUnavailableError,
    NasdaqDirectory,
    NotNasdaqListedError,
    normalize_symbol,
    parse_nasdaq_listed,
)


def test_parse_skips_test_issues_and_reads_fields() -> None:
    listings, created = parse_nasdaq_listed(SAMPLE_TEXT)
    assert "ZAZZT" not in listings
    apple = listings["AAPL"]
    assert apple.name == "Apple Inc."
    assert apple.security_type == "Common Stock"
    assert apple.market_tier == "Nasdaq Global Select Market"
    assert listings["QQQ"].is_etf is True
    assert listings["SMLC"].financial_status == "Deficient"
    assert created is not None and created.year == 2026 and created.month == 11


def test_parse_rejects_unknown_format() -> None:
    with pytest.raises(ValueError):
        parse_nasdaq_listed("<html>not the file</html>")


@pytest.mark.parametrize(
    "raw, expected", [("aapl", "AAPL"), (" $nvda ", "NVDA"), ("brk.b", "BRK.B")]
)
def test_normalize_symbol(raw: str, expected: str) -> None:
    assert normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "AAPL; DROP", "123", "TOOLONGSYMBOL"])
def test_normalize_symbol_rejects_garbage(raw: str) -> None:
    with pytest.raises(NotNasdaqListedError):
        normalize_symbol(raw)


def test_require_accepts_nasdaq_and_rejects_others(directory: NasdaqDirectory) -> None:
    assert directory.require("msft").symbol == "MSFT"
    with pytest.raises(NotNasdaqListedError, match="not listed on NASDAQ"):
        directory.require("IBM")  # NYSE-listed, not in the NASDAQ file


def test_search_ranks_exact_symbol_then_prefix_then_name(directory: NasdaqDirectory) -> None:
    assert [m.symbol for m in directory.search("AMD")][0] == "AMD"
    # Ticker prefix (APLD) ranks above a company-name match (Apple).
    assert [m.symbol for m in directory.search("ap")][:2] == ["APLD", "AAPL"]
    assert directory.search("nvidia")[0].symbol == "NVDA"
    assert directory.search("alphabet")[0].symbol == "GOOGL"
    assert directory.search("   ") == []


def test_search_prefers_common_stock_over_warrants(directory: NasdaqDirectory) -> None:
    assert [m.symbol for m in directory.search("small cap")] == ["SMLC", "SMLCW"]


def test_download_is_cached_on_disk(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str) -> str:
        calls.append(url)
        return SAMPLE_TEXT

    NasdaqDirectory(cache_dir=tmp_path, fetcher=fetch).load()
    assert (tmp_path / "nasdaqlisted.txt").exists()
    # A new instance reads the fresh cache instead of downloading again.
    NasdaqDirectory(cache_dir=tmp_path, fetcher=fetch).load()
    assert len(calls) == 1


def test_falls_back_to_stale_cache_when_download_fails(tmp_path: Path) -> None:
    cache = tmp_path / "nasdaqlisted.txt"
    cache.write_text(SAMPLE_TEXT, encoding="utf-8")
    old = time.time() - 3 * 24 * 3600
    os.utime(cache, (old, old))

    def broken(url: str) -> str:
        raise ConnectionError("offline")

    directory = NasdaqDirectory(cache_dir=tmp_path, fetcher=broken)
    assert directory.require("AAPL").name == "Apple Inc."


def test_no_cache_and_no_network_raises(tmp_path: Path) -> None:
    def broken(url: str) -> str:
        raise ConnectionError("offline")

    with pytest.raises(DirectoryUnavailableError):
        NasdaqDirectory(cache_dir=tmp_path, fetcher=broken).load()
