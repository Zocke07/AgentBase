"""Approval endpoints: the other half of the gate.

`POST /approvals/{id}` sets the future an agent is suspended on.
`GET /approvals` lists what is outstanding, including questions raised
before the window connected.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from agentbase.tools.approval import ApprovalNotPendingError, ApprovalScope

if TYPE_CHECKING:
    from agentbase.tools.approval import ApprovalRecord, ApprovalService

__all__ = ["router"]

router = APIRouter()


class ResolveApprovalRequest(BaseModel):
    """A decision on one approval. A misspelled field must not be read as a denial."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    #: How far a yes reaches: this call, or every call to the tool for the
    #: rest of the run. Ignored for a no, which is always for the one call.
    scope: Literal["call", "run"] = "call"


class ApprovalResponse(BaseModel):
    """One approval, as the dialog renders it."""

    id: str
    run_id: str
    tool: str
    args: dict[str, Any]
    risk: str
    status: str
    created_at: str
    resolved_at: str | None = None
    scope: Literal["call", "run"] = "call"


def _service(request: Request) -> ApprovalService:
    service: ApprovalService = request.app.state.approvals
    return service


def _response(record: ApprovalRecord) -> ApprovalResponse:
    return ApprovalResponse(
        id=record.id,
        run_id=record.run_id,
        tool=record.tool,
        args=record.args,
        risk=str(record.risk),
        status=str(record.status),
        created_at=record.created_at.isoformat(),
        resolved_at=record.resolved_at.isoformat() if record.resolved_at else None,
        scope="run" if record.scope is ApprovalScope.RUN else "call",
    )


@router.get("/approvals")
async def list_approvals(request: Request, run_id: str | None = None) -> list[ApprovalResponse]:
    """Every approval still waiting for an answer, oldest first."""
    records = await _service(request).store.list_pending(run_id)
    return [_response(record) for record in records]


@router.get("/approvals/{approval_id}")
async def get_approval(request: Request, approval_id: str) -> ApprovalResponse:
    record = await _service(request).store.get(approval_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No approval with id {approval_id!r}.")
    return _response(record)


@router.post("/approvals/{approval_id}")
async def resolve_approval(
    request: Request, approval_id: str, body: ResolveApprovalRequest
) -> ApprovalResponse:
    """Allow or deny a pending call, and release the agent waiting on it.

    404 for an unknown id; 409 for one already settled, so a second window's
    click reads as "already answered" rather than "gone".
    """
    service = _service(request)

    if await service.store.get(approval_id) is None:
        raise HTTPException(status_code=404, detail=f"No approval with id {approval_id!r}.")

    try:
        record = await service.resolve(
            approval_id, approved=body.approved, scope=ApprovalScope(body.scope)
        )
    except ApprovalNotPendingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _response(record)
