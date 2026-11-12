"""Audit trail of tool calls and approvals in Postgres (SCRUM-26, SCRUM-66).

Writing the audit log never breaks a chat: failures are logged and the answer continues.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from .approvals import ApprovalRequest

logger = logging.getLogger("stock_api.audit")

SCHEMA = """
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
CREATE INDEX IF NOT EXISTS tool_calls_conversation ON tool_calls (conversation_id, created_at);
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
"""

INSERT_TOOL_CALL = """
INSERT INTO tool_calls
    (conversation_id, call_id, tool, arguments, ok, error, source, as_of, latency_ms, approval_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

UPSERT_APPROVAL = """
INSERT INTO approvals
    (id, conversation_id, tool, arguments, reason, estimate, status, requested_at, decided_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, decided_at = EXCLUDED.decided_at
"""


class AuditLog(Protocol):
    async def tool_call(self, record: dict[str, Any]) -> None: ...

    async def approval(self, request: ApprovalRequest) -> None: ...


class MemoryAuditLog:
    def __init__(self) -> None:
        self.tool_calls: list[dict[str, Any]] = []
        self.approvals: list[dict[str, Any]] = []

    async def tool_call(self, record: dict[str, Any]) -> None:
        self.tool_calls.append(dict(record))

    async def approval(self, request: ApprovalRequest) -> None:
        self.approvals.append({"id": request.id, "tool": request.tool, "status": request.status})


def tool_call_params(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["conversation_id"],
        record.get("call_id"),
        record["tool"],
        json.dumps(record.get("arguments") or {}, default=str),
        bool(record["ok"]),
        record.get("error"),
        record.get("source"),
        record.get("as_of"),
        record.get("latency_ms"),
        record.get("approval_id"),
    )


def approval_params(request: ApprovalRequest) -> tuple[Any, ...]:
    return (
        request.id,
        request.conversation_id,
        request.tool,
        json.dumps(request.arguments, default=str),
        request.reason,
        request.estimate,
        request.status,
        request.requested_at,
        request.decided_at,
    )


class PostgresAuditLog:
    def __init__(self, database_url: str) -> None:
        self._url = database_url
        self._ready = False

    async def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        import psycopg

        try:
            async with await psycopg.AsyncConnection.connect(self._url, connect_timeout=3) as conn:
                if not self._ready:
                    await conn.execute(SCHEMA)
                    self._ready = True
                await conn.execute(sql, params)
                await conn.commit()
        except Exception as exc:  # noqa: BLE001 - auditing must not break the chat
            logger.warning("audit write failed: %s", exc)

    async def tool_call(self, record: dict[str, Any]) -> None:
        await self._execute(INSERT_TOOL_CALL, tool_call_params(record))

    async def approval(self, request: ApprovalRequest) -> None:
        await self._execute(UPSERT_APPROVAL, approval_params(request))
