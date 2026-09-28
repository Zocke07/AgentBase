"""Agent-definition endpoints and the editor's tool catalogue.

:mod:`agentbase.store.agents` owns the rules; this maps its errors to 4xx
``{message, field}`` responses. Reject unknown fields rather than dropping them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agentbase.store.agents import (
    AgentDef,
    AgentNotFoundError,
    AgentValidationError,
    BuiltinNotDeletableError,
    DuplicateAgentNameError,
)
from agentbase.store.spaces import SpaceNotFoundError
from agentbase.tools.catalogue import CATALOGUE

if TYPE_CHECKING:
    from agentbase.store.agents import AgentDefStore

__all__ = ["router"]

router = APIRouter()


class CreateAgentRequest(BaseModel):
    """New definition; callers cannot mint a built-in :class:`AgentDef`."""

    model_config = ConfigDict(extra="forbid")

    #: Roster to join; ``None`` selects the default space.
    space_id: str | None = None
    name: str
    role: str
    system_prompt: str
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    #: ``None`` inherits the workspace limit; a literal default might exceed it.
    max_steps: int | None = None
    auto_approve: list[str] = Field(default_factory=list)
    enabled: bool = True


class UpdateAgentRequest(BaseModel):
    """Partial update; omitted fields stay unchanged.

    ``None`` restores provider/model inheritance, so ``model_fields_set``
    distinguishes it from an omitted field.
    """

    model_config = ConfigDict(extra="forbid")

    #: Move to another roster; in-flight runs retain their snapshot.
    space_id: str | None = None
    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] | None = None
    max_steps: int | None = None
    auto_approve: list[str] | None = None
    enabled: bool | None = None


class CopyAgentRequest(BaseModel):
    """Copy destination. Copies get a new ID and are never built-ins."""

    space_id: str


class ToolResponse(BaseModel):
    """Catalogue entry rendered by the agent editor."""

    name: str
    description: str
    risk: str
    #: Whether the registry has an implementation for this catalogue name.
    available: bool


def _store(request: Request) -> AgentDefStore:
    store: AgentDefStore = request.app.state.agents
    return store


def _reject(exc: AgentValidationError) -> HTTPException:
    """Map validation failure to a field-aware 409 for duplicate names, else 400."""
    return HTTPException(
        status_code=409 if isinstance(exc, DuplicateAgentNameError) else 400,
        detail={"message": str(exc), "field": exc.field},
    )


@router.get("/agents")
async def list_agents(request: Request, space_id: str | None = None) -> list[AgentDef]:
    """List all definitions, including disabled ones, for the roster editor."""
    return await _store(request).list_all(space_id)


@router.get("/agents/{definition_id}")
async def get_agent(request: Request, definition_id: str) -> AgentDef:
    try:
        return await _store(request).require(definition_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agents", status_code=201)
async def create_agent(request: Request, body: CreateAgentRequest) -> AgentDef:
    try:
        return await _store(request).create(body.model_dump())
    except AgentValidationError as exc:
        raise _reject(exc) from exc
    except SpaceNotFoundError as exc:
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "field": "space_id"}
        ) from exc


@router.post("/agents/{definition_id}/copy", status_code=201)
async def copy_agent(request: Request, definition_id: str, body: CopyAgentRequest) -> AgentDef:
    """Copy a definition to another space's roster."""
    try:
        return await _store(request).copy(definition_id, body.space_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SpaceNotFoundError as exc:
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "field": "space_id"}
        ) from exc
    except AgentValidationError as exc:
        raise _reject(exc) from exc


@router.patch("/agents/{definition_id}")
async def update_agent(
    request: Request, definition_id: str, body: UpdateAgentRequest
) -> AgentDef:
    """Apply a partial update; built-ins are editable but not deletable."""
    changes: dict[str, Any] = {field: getattr(body, field) for field in body.model_fields_set}
    if not changes:
        raise HTTPException(status_code=400, detail="no fields were supplied")

    try:
        return await _store(request).update(definition_id, changes)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SpaceNotFoundError as exc:
        raise HTTPException(
            status_code=400, detail={"message": str(exc), "field": "space_id"}
        ) from exc
    except AgentValidationError as exc:
        raise _reject(exc) from exc


@router.delete("/agents/{definition_id}", status_code=204)
async def delete_agent(request: Request, definition_id: str) -> Response:
    try:
        await _store(request).delete(definition_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BuiltinNotDeletableError as exc:
        # 409, not 403: authority is valid; this row cannot be deleted.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(status_code=204)


@router.get("/tools")
async def list_tools(request: Request) -> list[ToolResponse]:
    """List tools and risk levels for editor checkboxes."""
    available = request.app.state.tool_runtime.tools
    return [
        ToolResponse(
            name=tool.name,
            description=tool.description,
            risk=str(tool.risk),
            available=tool.name in available,
        )
        for tool in CATALOGUE
    ]
