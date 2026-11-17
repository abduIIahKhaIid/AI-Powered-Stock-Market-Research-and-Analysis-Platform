"""Durable market data: ohlcv_daily and financial_facts (SCRUM-23).

The MCP server writes every daily candle it fetches and every SEC statement line item it
reads, and serves saved candles when the live sources fail.

Revision ID: 0002_market_data
Revises: 0001_baseline
Create Date: 2026-11-17
"""

from alembic import op

revision = "0002_market_data"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ohlcv_daily (
            symbol TEXT NOT NULL,
            day DATE NOT NULL,
            open NUMERIC(18, 6) NOT NULL,
            high NUMERIC(18, 6) NOT NULL,
            low NUMERIC(18, 6) NOT NULL,
            close NUMERIC(18, 6) NOT NULL,
            volume BIGINT NOT NULL,
            source TEXT NOT NULL,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (symbol, day)
        );
        CREATE INDEX ohlcv_daily_day ON ohlcv_daily (day);
        CREATE TABLE financial_facts (
            symbol TEXT NOT NULL,
            cik INTEGER NOT NULL,
            statement TEXT NOT NULL,
            frequency TEXT NOT NULL,
            period_end DATE NOT NULL,
            period_start DATE,
            item TEXT NOT NULL,
            value DOUBLE PRECISION NOT NULL,
            concept TEXT,
            form TEXT,
            filed DATE,
            link TEXT,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (symbol, statement, frequency, period_end, item)
        );
        CREATE INDEX financial_facts_cik ON financial_facts (cik, period_end);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financial_facts; DROP TABLE IF EXISTS ohlcv_daily;")
