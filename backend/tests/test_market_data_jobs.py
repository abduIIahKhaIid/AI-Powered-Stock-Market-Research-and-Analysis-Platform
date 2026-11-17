"""SCRUM-23: migrations, the watched-symbols refresh and hiding maintenance tools."""

import io
import os
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from financial_mcp.market_data import Candle
from financial_mcp.store import PostgresMarketStore
from stock_api import worker
from stock_api.agent.policy import ToolPolicy
from stock_api.agent.toolbox import ToolOutcome, ToolSpec
from stock_api.jobs.registry import DEFAULT_WATCHLIST, build_registry
from stock_api.jobs.runner import execute
from stock_api.jobs.store import MemoryJobStore

BACKEND = Path(__file__).resolve().parents[1]


def alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def test_migrations_render_the_market_data_tables_offline() -> None:
    out = io.StringIO()
    config = alembic_config("postgresql://user:pass@localhost/db")
    config.output_buffer = out
    with redirect_stdout(out):
        command.upgrade(config, "head", sql=True)
    sql = out.getvalue()
    for table in ("tool_calls", "approvals", "analysis_jobs", "ohlcv_daily", "financial_facts"):
        assert f"TABLE IF NOT EXISTS {table}" in sql or f"CREATE TABLE {table}" in sql
    assert "PRIMARY KEY (symbol, day)" in sql


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs a Postgres test database")
def test_migrations_and_the_market_store_on_postgres() -> None:
    import psycopg

    url = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        for table in ("ohlcv_daily", "financial_facts", "alembic_version"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    config = alembic_config(url)
    command.upgrade(config, "head")

    store = PostgresMarketStore(url)
    candles = [
        Candle("2026-11-12", 100.0, 103.0, 99.0, 102.5, 1_000),
        Candle("2026-11-13", 102.5, 104.0, 101.0, 103.25, 2_000),
    ]
    assert store.save_candles("AAPL", candles, "Yahoo") == 2
    store.save_candles("AAPL", [Candle("2026-11-13", 1, 2, 0.5, 1.5, 7)], "Alpha Vantage")
    loaded, source = store.load_candles("AAPL", date(2026, 11, 1))
    assert [c.close for c in loaded] == [102.5, 1.5] and source == "Alpha Vantage"

    statement = {
        "statement": "income",
        "freq": "annual",
        "periods": [
            {
                "end": "2024-09-28",
                "start": "2023-10-01",
                "form": "10-K",
                "filed": "2024-11-01",
                "link": "https://www.sec.gov/x",
                "values": {"revenue": 400e9, "net_income": 100e9},
                "tags": {"revenue": "Revenues"},
            }
        ],
    }
    assert store.save_statement("AAPL", 320193, statement) == 2
    assert store.save_statement("AAPL", 320193, statement) == 2  # an upsert, not a duplicate
    with psycopg.connect(url) as conn:
        count = conn.execute("SELECT count(*) FROM financial_facts").fetchone()
    assert count == (2,)

    command.downgrade(config, "0001_baseline")
    command.upgrade(config, "head")


class Runner:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    def __call__(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        assert name == "refresh_market_data"
        symbol = arguments["symbol"]
        self.symbols.append(symbol)
        if symbol == "TSLA":
            return ToolOutcome.failure(name, arguments, "No price data returned for TSLA.")
        data = {"daily_bars": 250, "facts_saved": 120, "last_bar": "2026-11-13"}
        return ToolOutcome(name, arguments, ok=True, payload={"data": data})


def test_the_watchlist_refresh_job() -> None:
    runner = Runner()
    registry = build_registry(runner, watchlist=("AAPL", "TSLA"))
    store = MemoryJobStore()
    job = store.create("refresh_watchlist", {})  # how Celery Beat creates it
    done = execute(job.id, store, registry)
    assert done.status == "succeeded" and runner.symbols == ["AAPL", "TSLA"]
    assert done.result["refreshed"]["AAPL"]["facts_saved"] == 120
    assert done.result["errors"] == {"TSLA": "No price data returned for TSLA."}
    assert done.summary == "Refreshed 1 symbols"
    assert registry["refresh_watchlist"].queue == "ingest"
    assert "AAPL" in DEFAULT_WATCHLIST


def test_beat_refreshes_the_watched_symbols_after_the_close() -> None:
    entry = worker.celery_app.conf.beat_schedule["refresh-watched-symbols"]
    assert entry["task"] == "jobs.scheduled" and entry["args"] == ("refresh_watchlist",)
    assert entry["schedule"].hour == {21} and entry["options"] == {"queue": "ingest"}


def test_maintenance_tools_are_hidden_from_the_model() -> None:
    specs = [ToolSpec("get_quote", ""), ToolSpec("refresh_market_data", ""), ToolSpec("ping", "")]
    assert [spec.name for spec in ToolPolicy().visible(specs)] == ["get_quote"]
