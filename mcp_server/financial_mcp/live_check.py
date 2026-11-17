"""Manual check against the real data sources (needs internet access).

docker compose exec mcp python -m financial_mcp.live_check AAPL
python -m financial_mcp.live_check nvidia      # outside Docker, from mcp_server/
docker compose exec mcp python -m financial_mcp.live_check AAPL --alpha-vantage
    (also calls Alpha Vantage: 2 of the 25 free requests a day, then cached)
"""

import json
import sys

from financial_mcp.alpha_vantage import AlphaVantagePrices
from financial_mcp.server import get_company_overview, get_price_history, get_quote, search_symbol
from financial_mcp.services import get_services


def check_alpha_vantage(symbol: str) -> int:
    client = get_services().alpha_vantage
    if client is None:
        print("\nAlpha Vantage: ALPHAVANTAGE_API_KEY is not set.")
        return 1
    candles = AlphaVantagePrices(client).history(symbol, "1mo", "1d")
    print(
        f"\nAlpha Vantage daily bars: {len(candles)}, last {candles[-1].time} "
        f"close {candles[-1].close}"
    )
    overview = get_company_overview(symbol)["data"]
    print(f"get_company_overview: {overview['name']}, {overview['sector']}, {overview['industry']}")
    print(f"Alpha Vantage requests used today: {client.calls_today()}")
    return 0


def main(argv: list[str]) -> int:
    flags = {arg for arg in argv[1:] if arg.startswith("--")}
    argv = [arg for arg in argv if not arg.startswith("--")]
    query = argv[1] if len(argv) > 1 else "AAPL"
    found = search_symbol(query, limit=3)
    print("search_symbol:", json.dumps(found, indent=2)[:1500])
    matches = found["data"]["matches"]
    if not matches:
        print(f"No NASDAQ match for '{query}'.")
        return 1
    symbol = matches[0]["symbol"]
    print("\nget_quote:", json.dumps(get_quote(symbol), indent=2))
    history = get_price_history(symbol, period="1mo", interval="1d")
    candles = history["data"]["candles"]
    print(
        f"\nget_price_history: {history['data']['count']} candles, "
        f"first {candles[0]['time']}, last {candles[-1]['time']}, as_of {history['as_of']}"
    )
    if "--alpha-vantage" in flags:
        return check_alpha_vantage(symbol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
