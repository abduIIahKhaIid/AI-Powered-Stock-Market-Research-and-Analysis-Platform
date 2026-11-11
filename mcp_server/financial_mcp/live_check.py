"""Manual check against the real data sources (needs internet access).

docker compose exec mcp python -m financial_mcp.live_check AAPL
python -m financial_mcp.live_check nvidia      # outside Docker, from mcp_server/
"""

import json
import sys

from financial_mcp.server import get_price_history, get_quote, search_symbol


def main(argv: list[str]) -> int:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
