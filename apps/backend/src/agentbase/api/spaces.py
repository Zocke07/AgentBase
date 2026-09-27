"""Space endpoints: CRUD over `spaces`, plus what a new space starts with.

The rules live in :mod:`agentbase.store.spaces`; this maps each refusal to a
status code and a `{message, field}` body.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agentbase.providers.catalog import equivalent
from agentbase.providers.factory import SUPPORTED_PROVIDERS
from agentbase.store.agents import AgentDef
from agentbase.store.settings import default_model_for
from agentbase.store.spaces import (
    DEFAULT_SPACE_ID,
    DefaultSpaceProtectedError,
    Space,
    SpaceHasRunsError,
    SpaceNotFoundError,
    SpaceValidationError,
)
from agentbase.tools.catalogue import RiskLevel, ToolPolicy

if TYPE_CHECKING:
    from agentbase.store.agents import AgentDefStore
    from agentbase.store.settings import SettingsStore
    from agentbase.store.spaces import SpaceStore

__all__ = ["router"]

router = APIRouter()


class CopyFrom(BaseModel):
    """Seed a new space with copies of another space's roster."""

    copy_from: str


class CreateSpaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    description: str = ""
    #: Provider and model. A space names both: an omitted provider is the
    #: app-wide one for new spaces, an omitted model that provider's default.
    provider: str | None = None
    model: str | None = None
    #: How the roster starts: empty, fresh copies of the three starter roles,
    #: or copies of another space's definitions.
    seed: Literal["empty", "builtins"] | CopyFrom = "builtins"


class UpdateSpaceRequest(BaseModel):
    """A partial update. ``None`` means "inherit", so `model_fields_set` tells it from "not sent".

    The provider cannot be cleared: a space names its own.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = None
    provider: str | None = None
    model: str | None = None
    auto_approve: list[RiskLevel] | None = None
    tool_policies: dict[str, ToolPolicy] | None = None
    max_steps_per_agent: int | None = Field(default=None, ge=1)
    max_agents_per_run: int | None = Field(default=None, ge=1)
    max_run_seconds: int | None = Field(default=None, ge=1)
    max_run_cost_micros: int | None = Field(default=None, ge=0)
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


def _settings(request: Request) -> SettingsStore:
    store: SettingsStore = request.app.state.settings
    return store


async def _with_model(request: Request, changes: dict[str, Any], current: Space | None) -> None:
    """Fill in the provider and model a space must name.

    A new space without a provider starts on the app-wide one, and a PATCH
    cannot clear it. A provider change without a model maps the current model
    to the same tier on the new provider (`catalog.equivalent`), so a switch
    does not jump to a different class of model. A create without a model, or
    a null-model PATCH, takes the provider's default. Ollama models are typed,
    so an existing space keeps its model until one is.
    """
    if "provider" in changes and changes["provider"] is None:
        if current is not None:
            raise _reject("A space names its provider. Choose one.", "provider")
        del changes["provider"]
    app_provider = (await _settings(request).get()).provider
    if current is None:
        changes.setdefault("provider", app_provider)
    # A row from before migration 016 may still read null: it ran on the app-wide one.
    was = (current.provider if current is not None else None) or app_provider
    provider: str = changes.get("provider", was)

    if changes.get("model") is not None:
        return
    if current is not None and "provider" in changes and provider != was:
        mapped = equivalent(current.model, was, provider)
        if mapped is not None:
            changes["model"] = mapped
        return
    if current is not None and "model" not in changes:
        return
    fallback = default_model_for(provider)
    if fallback is not None:
        changes["model"] = fallback
    elif current is None:
        changes["model"] = None


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
    fields: dict[str, Any] = {"name": body.name, "description": body.description}
    if body.provider is not None:
        fields["provider"] = body.provider
    if body.model is not None:
        fields["model"] = body.model
    await _with_model(request, fields, None)
    try:
        space = await store.create(fields)
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
        await _with_model(request, changes, await store.require(space_id))
        return _respond(store, await store.update(space_id, changes))
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DefaultSpaceProtectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SpaceValidationError as exc:
        raise _reject(str(exc), exc.field) from exc


class AgentMove(BaseModel):
    """One agent a provider switch would leave on the old provider's model."""

    id: str
    name: str
    #: What it names now; ``None`` follows the space.
    provider: str | None
    model: str | None
    #: The model it would name after moving; ``None`` follows the space.
    to_model: str | None


class ProviderSwitchPlan(BaseModel):
    """What moving a space to ``provider`` would change, before it is saved."""

    provider: str
    #: The space's model on the new provider; ``None`` where one must be typed.
    model: str | None
    #: Agents naming the current provider or one of its models.
    agents: list[AgentMove]


@router.get("/spaces/{space_id}/provider-switch")
async def plan_provider_switch(
    request: Request, space_id: str, provider: str
) -> ProviderSwitchPlan:
    """Preview a provider switch: the space's mapped model and the agents it strands.

    An agent that names the old provider, or a model while following the
    space's provider, would ask the new provider for a model it does not
    serve. Space settings lists these with their tier-mapped models and moves
    the ones the person keeps ticked, through the ordinary agent update.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise _reject(f"unknown provider {provider!r}", "provider")
    try:
        space = await _spaces(request).require(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    was = space.provider or (await _settings(request).get()).provider
    if provider == was:
        return ProviderSwitchPlan(provider=provider, model=space.model, agents=[])
    stranded = [
        definition
        for definition in await _agents(request).list_all(space_id)
        if definition.provider == was
        or (definition.provider is None and definition.model is not None)
    ]
    return ProviderSwitchPlan(
        provider=provider,
        model=equivalent(space.model, was, provider),
        agents=[
            AgentMove(
                id=definition.id,
                name=definition.name,
                provider=definition.provider,
                model=definition.model,
                to_model=None
                if definition.model is None
                else equivalent(definition.model, was, provider),
            )
            for definition in stranded
        ],
    )


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
    """Add the starter roles an existing roster lacks. Safe to press twice."""
    try:
        return await _agents(request).seed_builtins(space_id)
    except SpaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
