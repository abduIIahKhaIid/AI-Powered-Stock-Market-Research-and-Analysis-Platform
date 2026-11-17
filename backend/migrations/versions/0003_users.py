"""Accounts and job owners (SCRUM-40).

users holds sign-in accounts (scrypt password hashes); analysis_jobs.owner records which
user started a job, so each user sees only their own jobs and saved analyses.

Revision ID: 0003_users
Revises: 0002_market_data
Create Date: 2026-11-18
"""

from alembic import op

revision = "0003_users"
down_revision = "0002_market_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users (lower(username));
        ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS owner TEXT;
        CREATE INDEX IF NOT EXISTS analysis_jobs_owner ON analysis_jobs (owner, created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX IF EXISTS analysis_jobs_owner;
        ALTER TABLE analysis_jobs DROP COLUMN IF EXISTS owner;
        DROP TABLE IF EXISTS users;
        """
    )
