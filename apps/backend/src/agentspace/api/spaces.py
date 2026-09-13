"""Space endpoints: CRUD over `spaces`, plus what a new space starts with.

The rules live in :mod:`agentspace.store.spaces`; this maps each refusal to a
status code and a `{message, field}` body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agentspace.store.agents import AgentDef
from agentspace.store.spaces import (
    DEFAULT_SPACE_ID,
    DefaultSpaceProtectedError,
    Space,
    SpaceHasRunsError,
    SpaceNotFoundError,
    SpaceValidationError,
)
from agentspace.tools.catalogue import RiskLevel

if TYPE_CHECKING:
    from agentspace.store.agents import AgentDefStore
    from agentspace.store.spaces import SpaceStore

__all__ = ["router"]

router = APIRouter()


class CopyFrom(BaseModel):
    """Seed a new space with copies of another space's roster."""

    copy_from: str


class CreateSpaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    #: How the roster starts: empty, fresh copies of the three seeded roles,
    #: or copies of another space's definitions.
    seed: Literal["empty", "builtins"] | CopyFrom = "builtins"


class UpdateSpaceRequest(BaseModel):
    """A partial update. ``None`` means "inherit", so `model_fields_set` tells it from "not sent"."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = None
    provider: str | None = None
    model: str | None = None
    auto_approve: list[RiskLevel] | None = None
    max_steps_per_agent: int | None = Field(default=None, ge=1)
    max_agents_per_run: int | None = Field(default=None, ge=1)
    max_run_seconds: int | None = Field(default=None, ge=1)
    archived: bool | None = None


class SpaceResponse(Space):
    """A space, plus where its runs read and write."""

    #: The sandbox root for this space's runs; shown and opened, never written, by its page.
    folder: str
    #: The space that cannot be archived or deleted.
    is_default: bool


def _spaces(request: Request) -> SpaceStore:
    store: SpaceStore = request.app.state.spaces
    return store


def _agents(request: Request) -> AgentDefStore:
    store: AgentDefStore = request.app.state.agents
    return store


def _reject(message: str, field: str | None) -> HTTPException:
    return HTTPException(status_code=400, detail={"message": message, "field": field})


def _respond(store: SpaceStore, space: Space) -> SpaceResponse:
    return SpaceResponse(
        **space.model_dump(),
        folder=str(store.folder_for(space.id)),
        is_default=space.id == DEFAULT_SPACE_ID,
    )


@router.get("/spaces")
async def list_spaces(request: Request) -> list[SpaceResponse]:
    """Every space, archived ones included: their runs are still viewable."""
    store = _spaces(request)
    return [_respond(store, space) for space in await store.list_all()]


@router.get("/spaces/{space_id}")
async def get_space(request: Request, space_id: str) -> SpaceResponse:
    store = _spaces(request)
    try:
        return _respond(store, await store.require(space_id))
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/spaces", status_code=201)
async def create_space(request: Request, body: CreateSpaceRequest) -> SpaceResponse:
    """Create a space and seed its roster.

    The seed is its own write after the row exists, so a partial copy leaves
    a space the user can see and fix.
    """
    store = _spaces(request)
    try:
        space = await store.create({"name": body.name, "description": body.description})
    except SpaceValidationError as exc:
        raise _reject(str(exc), exc.field) from exc

    agents = _agents(request)
    if body.seed == "builtins":
        await agents.seed_builtins(space.id)
    elif isinstance(body.seed, CopyFrom):
        try:
            await agents.copy_roster(body.seed.copy_from, space.id)
        except SpaceNotFoundError as exc:
            raise _reject(str(exc), "seed") from exc

    return _respond(store, space)


@router.patch("/spaces/{space_id}")
async def update_space(
    request: Request, space_id: str, body: UpdateSpaceRequest
) -> SpaceResponse:
    changes: dict[str, Any] = {name: getattr(body, name) for name in body.model_fields_set}
    if not changes:
        raise _reject("no changes were supplied", None)

    store = _spaces(request)
    try:
        return _respond(store, await store.update(space_id, changes))
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DefaultSpaceProtectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SpaceValidationError as exc:
        raise _reject(str(exc), exc.field) from exc


@router.delete("/spaces/{space_id}", status_code=204)
async def delete_space(request: Request, space_id: str) -> Response:
    """Delete an empty space and its agents. 409 for the default, or one with runs."""
    try:
        await _spaces(request).delete(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (DefaultSpaceProtectedError, SpaceHasRunsError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/spaces/{space_id}/seed", status_code=201)
async def seed_space(request: Request, space_id: str) -> list[AgentDef]:
    """Add the seeded roles an existing roster lacks. Safe to press twice."""
    try:
        return await _agents(request).seed_builtins(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
