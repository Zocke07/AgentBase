"""Agent definition endpoints, and the tool catalogue the editor needs.

§5 Phase 5's acceptance criterion begins "an agent created entirely through the
API — never touching Python". This module is that API.

**Every rejection is a 4xx with a message written for a person**, per §5 Phase
5: "Reject at the API layer with a readable message, not a 500." The rules
themselves live in :mod:`agentspace.store.agents`, where they guard the only
place a row can be written; what happens here is the mapping from those errors
to status codes, and the `field` that lets Phase 7 put the message on the input
that caused it rather than in a toast that loses which one was wrong.

**Unknown fields are rejected rather than ignored.** Same reasoning as
`PATCH /settings`: Pydantic's default is to drop them, which turns a misspelled
field into a `200 OK` that changed nothing. That exact bug shipped once in this
project already (CLAUDE.md, Phase 4).
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
from agentspace.tools.catalogue import CATALOGUE

if TYPE_CHECKING:
    from agentspace.store.agents import AgentDefStore

__all__ = ["router"]

router = APIRouter()


class CreateAgentRequest(BaseModel):
    """A new definition.

    Deliberately not the same model as :class:`~agentspace.store.agents.AgentDef`:
    `id`, `created_at`, `updated_at` and `is_builtin` are ours to assign, and a
    request model that accepted them would let a caller mint a built-in — which
    is a definition the delete path refuses to remove.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    role: str
    system_prompt: str
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] = Field(default_factory=list)
    #: ``None`` means "whatever this workspace allows" — see
    #: :data:`agentspace.store.agents.DEFAULT_AGENT_MAX_STEPS`. Defaulting to a
    #: literal here would reject a definition for a field the caller never sent,
    #: whenever the workspace cap is below that literal.
    max_steps: int | None = None
    auto_approve: list[str] = Field(default_factory=list)
    enabled: bool = True


class UpdateAgentRequest(BaseModel):
    """A partial update. Every field optional; omitted fields are untouched.

    ``None`` is meaningful for `provider` and `model` — it is how a definition
    goes back to inheriting the workspace default — so this cannot use
    `exclude_none` the way `PATCH /settings` does. `model_fields_set` is what
    separates "sent as null" from "not sent".
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    provider: str | None = None
    model: str | None = None
    allowed_tools: list[str] | None = None
    max_steps: int | None = None
    auto_approve: list[str] | None = None
    enabled: bool | None = None


class ToolResponse(BaseModel):
    """One catalogue entry, as the agent editor renders it."""

    name: str
    description: str
    risk: str
    #: Whether an implementation is actually registered behind the name.
    #:
    #: False for every tool in Phase 5, and read from the registry rather than
    #: hardcoded now that Phase 6 has flipped it. Computed rather than asserted
    #: because the failure it guards against is a catalogue entry with no
    #: implementation — a tool the editor offers, a definition can allow, and a
    #: run then refuses. `test_every_catalogue_tool_has_an_implementation` pins
    #: the two together, and this reports the truth either way.
    available: bool


def _store(request: Request) -> AgentDefStore:
    store: AgentDefStore = request.app.state.agents
    return store


def _reject(exc: AgentValidationError) -> HTTPException:
    """Map a validation failure onto a status code and a field-aware body.

    A duplicate name is a 409 because it is a conflict with existing state that
    the caller can resolve by choosing another name; everything else is a 400,
    because the input itself is wrong.
    """
    return HTTPException(
        status_code=409 if isinstance(exc, DuplicateAgentNameError) else 400,
        detail={"message": str(exc), "field": exc.field},
    )


@router.get("/agents")
async def list_agents(request: Request) -> list[AgentDef]:
    """Every definition, enabled or not — this backs the roster editor.

    A run reads only the enabled ones; see
    :meth:`agentspace.orchestrator.registry.AgentRegistry.load`.
    """
    return await _store(request).list_all()


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


@router.patch("/agents/{definition_id}")
async def update_agent(
    request: Request, definition_id: str, body: UpdateAgentRequest
) -> AgentDef:
    """Apply a partial update.

    A built-in is editable here — §5 Phase 5 guards only the delete path — so
    there is deliberately no `is_builtin` check.
    """
    changes: dict[str, Any] = {field: getattr(body, field) for field in body.model_fields_set}
    if not changes:
        raise HTTPException(status_code=400, detail="no fields were supplied")

    try:
        return await _store(request).update(definition_id, changes)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentValidationError as exc:
        raise _reject(exc) from exc


@router.delete("/agents/{definition_id}", status_code=204)
async def delete_agent(request: Request, definition_id: str) -> Response:
    try:
        await _store(request).delete(definition_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BuiltinNotDeletableError as exc:
        # 409 rather than 403: nothing about the caller's authority is wrong,
        # the definition is simply not a thing that can be deleted. The message
        # says what to do instead.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(status_code=204)


@router.get("/tools")
async def list_tools(request: Request) -> list[ToolResponse]:
    """The tool catalogue, with each tool's risk level.

    §5 Phase 7 requires the agent editor's "tool checkboxes show each tool's
    risk level next to it, so the consequence of ticking `run_shell` is visible
    at the moment of ticking it". A UI hardcoding that list would drift from
    the catalogue the validator actually uses, so it reads this instead.
    """
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
