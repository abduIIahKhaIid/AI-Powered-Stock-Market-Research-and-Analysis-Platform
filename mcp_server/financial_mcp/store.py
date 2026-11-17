"""Durable market data in Postgres (SCRUM-23, SCRUM-59).

`ohlcv_daily` keeps every daily candle fetched, and `financial_facts` every line item of the
SEC statements read. The tables are created by the Alembic migrations in backend/migrations.
Writes are best effort: if Postgres is not reachable the tools still answer.
"""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any, Protocol

from .market_data import Candle

logger = logging.getLogger("financial_mcp.store")


class MarketStore(Protocol):
    def save_candles(self, symbol: str, candles: list[Candle], source: str) -> int: ...

    def load_candles(self, symbol: str, since: date) -> tuple[list[Candle], str | None]: ...

    def save_statement(self, symbol: str, cik: int, data: dict[str, Any]) -> int: ...


def fact_rows(symbol: str, cik: int, data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per line item per period of a build_statement result."""
    rows = []
    for period in data["periods"]:
        for item, value in period["values"].items():
            if value is None:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "cik": cik,
                    "statement": data["statement"],
                    "frequency": data["freq"],
                    "period_end": period["end"],
                    "period_start": period.get("start"),
                    "item": item,
                    "value": float(value),
                    "concept": period.get("tags", {}).get(item),
                    "form": period.get("form"),
                    "filed": period.get("filed"),
                    "link": period.get("link"),
                }
            )
    return rows


class MemoryMarketStore:
    def __init__(self) -> None:
        self.candles: dict[tuple[str, str], tuple[Candle, str]] = {}
        self.facts: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def save_candles(self, symbol: str, candles: list[Candle], source: str) -> int:
        with self._lock:
            for candle in candles:
                self.candles[(symbol, candle.time[:10])] = (candle, source)
        return len(candles)

    def load_candles(self, symbol: str, since: date) -> tuple[list[Candle], str | None]:
        rows = sorted(
            (
                (c, s)
                for (sym, day), (c, s) in self.candles.items()
                if sym == symbol and day >= since.isoformat()
            ),
            key=lambda row: row[0].time,
        )
        return [c for c, _ in rows], (rows[-1][1] if rows else None)

    def save_statement(self, symbol: str, cik: int, data: dict[str, Any]) -> int:
        rows = fact_rows(symbol, cik, data)
        with self._lock:
            for row in rows:
                key = (symbol, row["statement"], row["frequency"], row["period_end"], row["item"])
                self.facts[key] = row
        return len(rows)


class PostgresMarketStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(self.database_url, connect_timeout=3)

    def save_candles(self, symbol: str, candles: list[Candle], source: str) -> int:
        if not candles:
            return 0
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ohlcv_daily (symbol, day, open, high, low, close, volume, source) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (symbol, day) DO UPDATE SET open = EXCLUDED.open, "
                "high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, "
                "volume = EXCLUDED.volume, source = EXCLUDED.source, fetched_at = now()",
                [
                    (symbol, c.time[:10], c.open, c.high, c.low, c.close, c.volume, source)
                    for c in candles
                ],
            )
        return len(candles)

    def load_candles(self, symbol: str, since: date) -> tuple[list[Candle], str | None]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT day, open, high, low, close, volume, source FROM ohlcv_daily "
                "WHERE symbol = %s AND day >= %s ORDER BY day",
                (symbol, since),
            ).fetchall()
        candles = [
            Candle(r[0].isoformat(), float(r[1]), float(r[2]), float(r[3]), float(r[4]), int(r[5]))
            for r in rows
        ]
        return candles, (rows[-1][6] if rows else None)

    def save_statement(self, symbol: str, cik: int, data: dict[str, Any]) -> int:
        rows = fact_rows(symbol, cik, data)
        if not rows:
            return 0
        columns = list(rows[0])
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO financial_facts ({', '.join(columns)}) "
                f"VALUES ({', '.join(['%s'] * len(columns))}) "
                "ON CONFLICT (symbol, statement, frequency, period_end, item) DO UPDATE SET "
                "value = EXCLUDED.value, concept = EXCLUDED.concept, form = EXCLUDED.form, "
                "filed = EXCLUDED.filed, link = EXCLUDED.link, fetched_at = now()",
                [tuple(row[c] for c in columns) for row in rows],
            )
        return len(rows)


class RecordingPrices:
    """Saves the daily candles a provider returns; serves saved ones when every source fails."""

    def __init__(self, provider: Any, store: MarketStore) -> None:
        self.provider = provider
        self.store = store
        self._local = threading.local()

    @property
    def source(self) -> str:
        return getattr(self._local, "source", self.provider.source)

    def history(self, symbol: str, period: str, interval: str) -> list[Candle]:
        from .alpha_vantage import _trim
        from .market_data import PriceDataError

        try:
            candles = self.provider.history(symbol, period, interval)
        except PriceDataError as exc:
            if interval != "1d" or period not in (
                "5d",
                "1mo",
                "3mo",
                "6mo",
                "ytd",
                "1y",
                "2y",
                "5y",
            ):
                raise
            saved = self._saved(symbol, period)
            if not saved:
                raise
            logger.warning("serving saved daily prices for %s: %s", symbol, exc)
            self._local.source = (
                f"Saved daily prices (ohlcv_daily, from {saved[1]}), used because live "
                f"sources failed"
            )
            return _trim(saved[0], period)
        self._local.source = self.provider.source
        if interval == "1d":
            try:
                self.store.save_candles(symbol, candles, self.provider.source)
            except Exception as exc:  # noqa: BLE001 - durable storage is best effort
                logger.warning("could not save candles for %s: %s", symbol, exc)
        return candles

    def _saved(self, symbol: str, period: str) -> tuple[list[Candle], str] | None:
        from datetime import timedelta

        try:
            candles, source = self.store.load_candles(symbol, date.today() - timedelta(days=1900))
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read saved candles for %s: %s", symbol, exc)
            return None
        return (candles, source or "earlier fetches") if candles else None

    def __getattr__(self, name: str) -> Any:
        return getattr(self.provider, name)
