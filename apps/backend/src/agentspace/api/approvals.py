"""Approval endpoints: the other half of the gate.

§3's layout names this module `POST /approvals/{id}`, and that is the endpoint
that matters: an agent inside a run is suspended on an `asyncio.Future`, and
this is what sets it. The two halves live in different requests, which is why
:class:`~agentspace.tools.approval.ApprovalService` is application state rather
than something a run owns.

`GET /approvals` exists for the Phase 7 dialog, which has to render what is
outstanding when it opens: including approvals raised before it connected. A
UI relying only on the `approval.requested` event would show nothing to a user
who opened the window a second too late, and the whole point of the gate is
that somebody is there to answer it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from agentspace.tools.approval import ApprovalNotPendingError

if TYPE_CHECKING:
    from agentspace.tools.approval import ApprovalRecord, ApprovalService

__all__ = ["router"]

router = APIRouter()


class ResolveApprovalRequest(BaseModel):
    """A decision on one approval.

    ``extra="forbid"`` for the reason every request model in this project has
    it: Pydantic's default is to drop an unknown field, which turned a
    misspelled setting into a `200 OK` that changed nothing once already
    (CLAUDE.md, Phase 4). Here the stakes are higher: a client that sent
    ``{"approve": true}`` would have the typo silently read as a denial.
    """

    model_config = ConfigDict(extra="forbid")

    approved: bool


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

    A 404 for an id that does not exist, and a **409** for one that is already
    settled. The distinction is not pedantry: two windows showing the same
    dialog is ordinary, and the second click has to fail in a way the UI can
    explain as "somebody already answered this" rather than as "that approval
    is gone".
    """
    service = _service(request)

    if await service.store.get(approval_id) is None:
        raise HTTPException(status_code=404, detail=f"No approval with id {approval_id!r}.")

    try:
        record = await service.resolve(approval_id, approved=body.approved)
    except ApprovalNotPendingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _response(record)
