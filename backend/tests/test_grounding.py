import pytest

from stock_api.agent.composer import (
    disclaimer_for,
    extract_assumptions,
    source_link,
)
from stock_api.agent.grounding import Evidence, check_answer, extract_numbers, remove_ungrounded

QUOTE = {
    "data": {
        "symbol": "NVDA",
        "price": 168.89,
        "open": 173.97,
        "volume": 429273200,
        "previous_close": 178.67,
        "change": -9.78,
        "change_percent": -5.47,
    },
    "source": "Yahoo Finance via yfinance",
    "as_of": "2026-11-10",
}
CLOSES = [340.97, 342.94, 343.91, 338.32, 331.90, 350.69, 348.51]
HISTORY = {"data": {"symbol": "AAPL", "candles": [{"close": c} for c in CLOSES]}}


def evidence(*payloads: object) -> Evidence:
    ev = Evidence()
    for payload in payloads:
        ev.add_payload(payload)
    return ev


def texts(answer: str) -> list[str]:
    return [m.text for m in extract_numbers(answer)]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Price $168.89, volume 429,273,200", ["$168.89", "429,273,200"]),
        ("Down ‑$9.78 (‑5.47 %)", ["‑$9.78", "‑5.47 %"]),
        ("Market cap $1.2B or 1.2 trillion", ["$1.2B", "1.2 trillion"]),
        ("As of 2026-11-10 and Nov 10, 2026 at 4:00 PM", []),
        ("In 2025 it had 3 splits and 2 tools", []),
        ("1. First point\n2. Second point", []),
        ("The 50-day average over 6 months, SMA 20 and RSI 14", []),
        ("The S&P 500 and Nasdaq-100 in Q3 2026", []),
        ("Periods 1M, 3M and 6M", []),
        ("For example, a $30 stock earning $2 has a P/E of 15.", []),
        ("Ticker BRK.B and ratio 45.2", ["45.2"]),
    ],
)
def test_extract_numbers(answer: str, expected: list[str]) -> None:
    assert texts(answer) == expected


def test_quoted_values_match_with_rounding_tolerance() -> None:
    ev = evidence(QUOTE)
    ok = "NVDA $168.89 ($168.9, about $169), volume 429.3 million, change -$9.78 (-5.47%)."
    assert check_answer(ok, ev).ok
    report = check_answer("NVDA traded at $170.00 with volume 430 million.", ev)
    assert report.unverified_texts() == ["$170.00", "430 million"]


def test_percent_stored_as_fraction_matches() -> None:
    ev = evidence({"data": {"net_margin": 0.2534}})
    assert check_answer("Net margin was 25.3%.", ev).ok


def test_simple_calculations_on_tool_values_are_accepted() -> None:
    ev = evidence(HISTORY)
    # first to last: +7.54 USD, +2.21 %; range high/low: 5.66 %; last vs high: -0.62 %
    answer = "It rose $7.54 (2.21%) over the month; range 5.66%; now 0.62% below the high."
    assert check_answer(answer, ev).ok


def test_seeded_wrong_percentage_is_caught() -> None:
    # From the first live test: the model wrote 2.4 % for a 2.21 % move.
    report = check_answer("A rise of about 2.4 % over the month.", evidence(HISTORY))
    assert report.unverified_texts() == ["2.4 %"]


def test_numbers_from_question_and_history_are_allowed() -> None:
    ev = Evidence()
    ev.add_text("What if the price falls 12.5%?")
    assert check_answer("A 12.5% fall is a large move.", ev).ok


def test_stated_assumptions_are_not_checked() -> None:
    answer = "Scenario only.\n\n## Assumptions\n- Discount rate 8.5%\n- Growth 4% a year\n"
    assert check_answer(answer, Evidence()).ok


def test_remove_ungrounded_drops_sentences_and_blanks_table_cells() -> None:
    ev = evidence(QUOTE)
    answer = (
        "NVDA closed at $168.89. It has a P/E of 45.2 which is high. Volume 429,273,200.\n"
        "- Dividend yield 3.1%\n"
        "| Metric | NVDA |\n|---|---|\n| Price | $168.89 |\n| Beta | 1.75 |"
    )
    report = check_answer(answer, ev)
    assert report.unverified_texts() == ["45.2", "3.1%", "1.75"]
    cleaned = remove_ungrounded(answer, report.ungrounded)
    assert cleaned == (
        "NVDA closed at $168.89. Volume 429,273,200.\n"
        "| Metric | NVDA |\n|---|---|\n| Price | $168.89 |\n| Beta | n/a |"
    )
    assert check_answer(cleaned, ev).ok


def test_extract_assumptions_variants() -> None:
    assert extract_assumptions("Text\n\n**Assumptions**\n- A\n- B\n\nMore text\n- not this") == [
        "A",
        "B",
    ]
    assert extract_assumptions("### Assumptions\n1. Rate 8%\n2) Growth 3%") == [
        "Rate 8%",
        "Growth 3%",
    ]
    assert extract_assumptions("Assumptions: price stays flat") == ["price stays flat"]
    assert extract_assumptions("No list here") == []


def test_disclaimer_adds_projection_note_only_when_needed() -> None:
    assert "Projections" in disclaimer_for("What if AAPL grows?", "", [])
    assert "Projections" in disclaimer_for("q", "a", ["Growth 5%"])
    assert "Projections" in disclaimer_for("Agar price 10% gire to?", "", [])
    assert "Projections" not in disclaimer_for("NVDA price?", "NVDA is $168.89.", [])


def test_source_link_from_payload() -> None:
    assert source_link({"data": {"filing_url": "https://www.sec.gov/x"}}) == "https://www.sec.gov/x"
    assert source_link({"url": "javascript:alert(1)"}) is None
    assert source_link(QUOTE) is None


# --- written calculations and what-if scenarios (live test findings) ----------------------

NVDA_QUOTE = {
    "data": {"symbol": "NVDA", "price": 173.73, "previous_close": 168.89, "volume": 313417400},
    "source": "Yahoo Finance via yfinance",
}
VOLUMES = [25900600, 38983800, 50061100, 39767300, 59946400, 34573200, 35851400]
CANDLES = {
    "data": {"candles": [{"close": c, "volume": v} for c, v in zip(CLOSES, VOLUMES, strict=True)]}
}


def test_what_if_growth_projection_is_accepted() -> None:
    ev = evidence(NVDA_QUOTE)
    ev.add_text("What if NVIDIA grows 10% a year for 3 years?")
    answer = (
        "Base $173.73.\n"
        "Year 1: [ 173.73 \\times (1 + 0.10)^{1} = 191.103 ] so $191.10\n"
        "Year 2: 191.103 × 1.10 = 210.2133 ($210.21)\n"
        "Year 3: $231.23, total +33.10 %, gain $57.50.\n"
        "| End of 2028 (2 yr) | $210.21 | +21.00 % |\n"
    )
    assert check_answer(answer, ev).ok


def test_growth_rate_from_stated_assumptions_is_used() -> None:
    answer = "**Assumptions**\n- Annual growth 10 %\n\nYear 1 price: $191.10 (+10.00 %)."
    assert check_answer(answer, evidence(NVDA_QUOTE)).ok


def test_correct_written_calculation_with_model_rounding_is_accepted() -> None:
    # 14.66 / 340.97 x 100 is 4.2995; the model wrote 4.2989 (within 0.1 %).
    answer = "| Pct | (14.66 / 340.97) × 100 = 4.2989 → 4.30 % |"
    ev = evidence({"data": {"candles": [{"close": 340.97}, {"close": 355.63}]}})
    assert check_answer(answer, ev).ok


def test_wrong_calculation_and_wrong_total_are_caught() -> None:
    ev = evidence(CANDLES)
    # 348.51 - 340.97 = 7.54 is supported; the result 4.9 is wrong (it is 2.21).
    assert check_answer("(7.54 / 340.97) × 100 = 4.9 %", ev).unverified_texts() == ["4.9 %"]
    total = f"{sum(VOLUMES):,}"
    assert check_answer(f"Total volume {total} shares.", ev).ok
    assert check_answer("Total volume 1,086,734,500 shares.", ev).unverified_texts() == [
        "1,086,734,500"
    ]


def test_made_up_figures_cannot_be_laundered_through_a_calculation() -> None:
    ev = evidence(NVDA_QUOTE)
    report = check_answer("NVDA will reach 999 × 1 = 999 and 173.73 × 1.5 = 260.60.", ev)
    assert report.unverified_texts() == ["999", "1.5", "260.60"]


def test_percent_claim_does_not_match_a_price_difference() -> None:
    # 355.63 - 350.69 = 4.94 USD must not make "4.9 %" look supported.
    ev = evidence({"data": {"candles": [{"close": 350.69}, {"close": 355.63}]}})
    assert check_answer("It moved 4.9 % on the last day.", ev).unverified_texts() == ["4.9 %"]
    assert check_answer("It moved $4.94 (1.41 %) on the last day.", ev).ok
