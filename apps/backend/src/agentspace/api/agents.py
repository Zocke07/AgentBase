"""Agent definition endpoints, and the tool catalogue the editor needs.

The rules live in :mod:`agentspace.store.agents`; this maps their errors to
4xx responses carrying `{message, field}` so the editor can put the message
on the offending input. Unknown fields are rejected rather than dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agentspace.store.agents import (
    AgentDef,
    AgentNotFoundError,
    AgentValidationError,
    BuiltinNotDeletableError,
    DuplicateAgentNameError,
)
from agentspace.store.spaces import SpaceNotFoundError
from agentspace.tools.catalogue import CATALOGUE

if TYPE_CHECKING:
    from agentspace.store.agents import AgentDefStore

__all__ = ["router"]

router = APIRouter()


class CreateAgentRequest(BaseModel):
    """A new definition.

    Not :class:`~agentspace.store.agents.AgentDef`: a caller must not mint a built-in.
    """

    model_config = ConfigDict(extra="forbid")

    #: The roster this definition joins. ``None`` is the default space.
    space_id: str | None = None
    name: str
    role: str
    system_prompt: str
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    #: ``None`` means "whatever this workspace allows"; a literal default here
    #: would be rejected whenever the workspace cap is below it.
    max_steps: int | None = None
    auto_approve: list[str] = Field(default_factory=list)
    enabled: bool = True


class UpdateAgentRequest(BaseModel):
    """A partial update. Every field optional; omitted fields are untouched.

    ``None`` is meaningful for `provider` and `model` (back to inheriting), so
    `model_fields_set` separates "sent as null" from "not sent".
    """

    model_config = ConfigDict(extra="forbid")

    #: A move to another space's roster; in-flight runs hold a snapshot.
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
    """Where the copy goes. A copy is a new row with a new id, never a built-in."""

    space_id: str


class ToolResponse(BaseModel):
    """One catalogue entry, as the agent editor renders it."""

    name: str
    description: str
    risk: str
    #: Whether an implementation is registered behind the name; read from the
    #: registry so a catalogue entry with none reports the truth.
    available: bool


def _store(request: Request) -> AgentDefStore:
    store: AgentDefStore = request.app.state.agents
    return store


def _reject(exc: AgentValidationError) -> HTTPException:
    """Map a validation failure onto a status code and a field-aware body: 409 for a duplicate
    name, else 400.
    """
    return HTTPException(
        status_code=409 if isinstance(exc, DuplicateAgentNameError) else 400,
        detail={"message": str(exc), "field": exc.field},
    )


@router.get("/agents")
async def list_agents(request: Request, space_id: str | None = None) -> list[AgentDef]:
    """Every definition, enabled or not: this backs the roster editor."""
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
    """A copy of one definition on another space's roster."""
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
    """Apply a partial update. A built-in is editable; only the delete path is guarded."""
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
        # 409, not 403: the caller's authority is fine; the row is not deletable.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(status_code=204)


@router.get("/tools")
async def list_tools(request: Request) -> list[ToolResponse]:
    """The tool catalogue with each tool's risk level, for the editor's checkboxes."""
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
