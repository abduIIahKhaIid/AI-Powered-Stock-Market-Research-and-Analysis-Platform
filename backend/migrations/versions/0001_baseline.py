"""Baseline: the tables the app created itself before migrations existed.

audit (tool_calls, approvals) from SCRUM-26 and analysis_jobs from SCRUM-32/34. Written with
IF NOT EXISTS so an existing database is adopted as it is.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-17
"""

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tool_calls (
            id BIGSERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            call_id TEXT,
            tool TEXT NOT NULL,
            arguments JSONB NOT NULL,
            ok BOOLEAN NOT NULL,
            error TEXT,
            source TEXT,
            as_of TEXT,
            latency_ms INTEGER,
            approval_id TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS tool_calls_conversation
            ON tool_calls (conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            tool TEXT NOT NULL,
            arguments JSONB NOT NULL,
            reason TEXT NOT NULL,
            estimate TEXT,
            status TEXT NOT NULL,
            requested_at TIMESTAMPTZ NOT NULL,
            decided_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS analysis_jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            params JSONB NOT NULL,
            conversation_id TEXT,
            status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0,
            stage TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            error TEXT,
            result JSONB,
            result_path TEXT,
            cancel_requested BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL,
            started_at TIMESTAMPTZ,
            finished_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS analysis_jobs_conversation
            ON analysis_jobs (conversation_id, created_at);
        CREATE INDEX IF NOT EXISTS analysis_jobs_status ON analysis_jobs (status, created_at);
        ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS retry_at TIMESTAMPTZ;
        ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS files JSONB NOT NULL DEFAULT '[]';
        ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS summary TEXT;
        ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
        CREATE UNIQUE INDEX IF NOT EXISTS analysis_jobs_idempotency_key
            ON analysis_jobs (idempotency_key) WHERE idempotency_key IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analysis_jobs; DROP TABLE IF EXISTS approvals;")
    op.execute("DROP TABLE IF EXISTS tool_calls;")
