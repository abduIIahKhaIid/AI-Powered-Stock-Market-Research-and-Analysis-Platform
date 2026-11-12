"""POST /approvals/{approval_id}: approve or deny a sensitive action (SCRUM-26)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel

from .agent.approvals import ApprovalAlreadyDecided, ApprovalBroker, ApprovalNotFound
from .agent.factory import get_approval_broker

router = APIRouter(tags=["approvals"])


class Decision(BaseModel):
    decision: Literal["approve", "deny"]


class DecisionResult(BaseModel):
    approval_id: str
    tool: str
    status: str


@router.post("/approvals/{approval_id}", response_model=DecisionResult)
async def decide(
    approval_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
    body: Decision,
    broker: Annotated[ApprovalBroker, Depends(get_approval_broker)],
) -> DecisionResult:
    try:
        request = broker.decide(approval_id, approve=body.decision == "approve")
    except ApprovalNotFound:
        raise HTTPException(status_code=404, detail="No such approval request.") from None
    except ApprovalAlreadyDecided as exc:
        raise HTTPException(
            status_code=409, detail=f"This request is already {exc.args[0]}."
        ) from None
    return DecisionResult(approval_id=request.id, tool=request.tool, status=request.status)
