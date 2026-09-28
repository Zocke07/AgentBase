"""Approval endpoints: the gate's HTTP half.

`POST /approvals/{id}` resolves the future suspending an agent; `GET` lists
outstanding questions, including ones raised before the window connected.
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
    """Decision on one approval; reject misspelled fields rather than deny."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    #: A yes applies to this call or the run's later calls to this tool. A no
    #: always applies only to this call.
    scope: Literal["call", "run"] = "call"


class ApprovalResponse(BaseModel):
    """Approval data rendered by the dialog."""

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
    """List unanswered approvals, oldest first."""
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
    """Resolve a pending call and release its agent.

    Unknown IDs return 404; settled ones return 409 so another window sees
    "already answered," not "gone."
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
