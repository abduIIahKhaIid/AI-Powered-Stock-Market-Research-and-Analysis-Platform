"""User approval for sensitive actions (SCRUM-26).

The agent opens a request and waits; POST /approvals/{id} settles it. Requests that get no
answer in time, or whose chat stream closes, expire and the action does not run.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

Status = Literal["pending", "approved", "denied", "expired"]


@dataclass
class ApprovalRequest:
    id: str
    conversation_id: str
    tool: str
    arguments: dict[str, Any]
    reason: str
    estimate: str | None = None
    status: Status = "pending"
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None


class ApprovalNotFound(KeyError):
    pass


class ApprovalAlreadyDecided(ValueError):
    pass


class ApprovalBroker:
    def __init__(self, timeout_seconds: float = 300.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._requests: dict[str, ApprovalRequest] = {}
        self._waiters: dict[str, asyncio.Future[bool]] = {}

    def open(
        self,
        conversation_id: str,
        tool: str,
        arguments: dict[str, Any],
        reason: str,
        estimate: str | None = None,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            tool=tool,
            arguments=arguments,
            reason=reason,
            estimate=estimate,
        )
        self._requests[request.id] = request
        self._waiters[request.id] = asyncio.get_running_loop().create_future()
        return request

    def get(self, approval_id: str) -> ApprovalRequest:
        try:
            return self._requests[approval_id]
        except KeyError:
            raise ApprovalNotFound(approval_id) from None

    def decide(self, approval_id: str, approve: bool) -> ApprovalRequest:
        request = self.get(approval_id)
        if request.status != "pending":
            raise ApprovalAlreadyDecided(request.status)
        request.status = "approved" if approve else "denied"
        request.decided_at = datetime.now(UTC)
        waiter = self._waiters.get(approval_id)
        if waiter is not None and not waiter.done():
            waiter.set_result(approve)
        return request

    async def wait(self, approval_id: str) -> Status:
        request = self.get(approval_id)
        waiter = self._waiters[approval_id]
        try:
            await asyncio.wait_for(asyncio.shield(waiter), timeout=self.timeout_seconds)
        except TimeoutError:
            self._expire(request)
        except asyncio.CancelledError:
            self._expire(request)  # the chat stream closed
            raise
        finally:
            self._waiters.pop(approval_id, None)
        return request.status

    def _expire(self, request: ApprovalRequest) -> None:
        if request.status == "pending":
            request.status = "expired"
            request.decided_at = datetime.now(UTC)
