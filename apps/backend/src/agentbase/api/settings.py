"""Settings and budget endpoints.

Never return a key. ``configured_secrets`` reports only names received over
stdin; read-back would let any loopback client exfiltrate credentials.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentbase import __version__
from agentbase.budget.ledger import current_period
from agentbase.budget.usage import UsageReport, UsageStore
from agentbase.channels.identity import ChannelIdentity
from agentbase.providers.base import ProviderAuthError
from agentbase.providers.catalog import Tier, catalog_for, equivalent
from agentbase.providers.chatgpt import ChatGPTRuntime, plan_models
from agentbase.providers.factory import (
    SUPPORTED_PROVIDERS,
    UnknownProviderError,
    build_provider,
    qualified_model,
)
from agentbase.providers.pricing import PRICES, format_micros, is_priced
from agentbase.secrets import SECRET_KEYS
from agentbase.store.settings import (
    ChannelApprovalPolicy,
    MemoryManagement,
    OpenAIAccess,
    WorkspaceSettings,
    default_model_for,
)
from agentbase.store.spaces import SpaceArchivedError, SpaceNotFoundError
from agentbase.tools.catalogue import RiskLevel, ToolPolicy

if TYPE_CHECKING:
    from agentbase.budget.ledger import BudgetLedger
    from agentbase.channels.service import ChannelService
    from agentbase.secrets import SecretStore
    from agentbase.store.settings import SettingsStore
    from agentbase.store.spaces import SpaceStore

__all__ = ["router"]

router = APIRouter()

#: Settings that affect connected adapters. Derive from the model so future
#: channel settings cannot be missed.
_CHANNEL_SETTINGS: frozenset[str] = frozenset(
    name for name in WorkspaceSettings.model_fields if name.startswith("discord_")
)


class SettingsResponse(BaseModel):
    """Workspace settings plus UI read-only facts."""

    settings: WorkspaceSettings
    #: Present API-key names; never values.
    configured_secrets: list[str]
    #: Every sidecar secret name, present or not.
    known_secrets: list[str]
    supported_providers: list[str]
    #: False means every run will be refused; show this before Start.
    model_is_priced: bool
    #: Sidecar release for About; identifies the sidecar that answered.
    version: str
    #: Database and space-folder location for About.
    data_dir: str


class UpdateSettingsRequest(BaseModel):
    """Partial update; omitted fields stay unchanged.

    Reject unknown fields: Pydantic would otherwise return ``200 OK`` for a
    misspelling. Mirror every :class:`~agentbase.store.settings.WorkspaceSettings`
    field here; bounds and optionality differ, and the paired test detects drift.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = Field(default=None, min_length=1)
    openai_access: OpenAIAccess | None = None
    monthly_cap_micros: int | None = Field(default=None, ge=0)
    ollama_base_url: str | None = Field(default=None, min_length=1)

    # Mirror `WorkspaceSettings` bounds: zero is not a stricter limit.
    max_steps_per_agent: int | None = Field(default=None, ge=1)
    max_agents_per_run: int | None = Field(default=None, ge=1)
    max_run_seconds: int | None = Field(default=None, ge=1)
    max_run_cost_micros: int | None = Field(default=None, ge=0)
    unattended_question_seconds: int | None = Field(default=None, ge=0)
    memory_management: MemoryManagement | None = None

    # An empty list disables pre-authorization; `exclude_none` distinguishes
    # it from an omitted field.
    auto_approve: list[RiskLevel] | None = None
    #: Replace the stored map wholesale; ``{}`` clears all per-tool answers.
    tool_policies: dict[str, ToolPolicy] | None = None
    #: Replace the list wholesale; ``[]`` makes every network call ask.
    auto_approve_hosts: list[str] | None = None

    # ``channel_identities: []`` revokes everyone, not an omitted field.
    discord_enabled: bool | None = None
    channel_identities: list[ChannelIdentity] | None = None
    channel_approvals: ChannelApprovalPolicy | None = None

    # Chat-run location. `exclude_none` rejects sent null, so an empty string
    # means the default space and is stored as null.
    channel_space_id: str | None = None

    onboarding_completed: bool | None = None


class BudgetResponse(BaseModel):
    period: str
    spent_micros: int
    cap_micros: int
    percent_used: int
    spent_display: str
    cap_display: str
    #: This space's period spend; caps are app-wide, not per-space.
    space_spent_micros: int | None = None
    space_spent_display: str | None = None


def _settings_store(request: Request) -> SettingsStore:
    store: SettingsStore = request.app.state.settings
    return store


def _secrets(request: Request) -> SecretStore:
    secrets: SecretStore = request.app.state.secrets
    return secrets


def _ledger(request: Request) -> BudgetLedger:
    ledger: BudgetLedger = request.app.state.ledger
    return ledger


async def _new_space_model(request: Request, provider: str, openai_access: str) -> str:
    """The model a new space on ``provider`` starts on: the default tier, kept
    to what a ChatGPT plan includes when one limits the provider."""
    fallback = default_model_for(provider) or ""
    included = await plan_models(provider, openai_access, _chatgpt_runtime(request))
    if included is None:
        return fallback
    return equivalent(None, provider, provider, included) or fallback


def _chatgpt_runtime(request: Request) -> ChatGPTRuntime:
    runtime: ChatGPTRuntime = request.app.state.chatgpt_runtime
    return runtime


def _spaces(request: Request) -> SpaceStore:
    spaces: SpaceStore = request.app.state.spaces
    return spaces


async def _response(request: Request, settings: WorkspaceSettings) -> SettingsResponse:
    return SettingsResponse(
        settings=settings,
        configured_secrets=list(_secrets(request).names),
        known_secrets=sorted(SECRET_KEYS),
        supported_providers=sorted(SUPPORTED_PROVIDERS),
        # Price the provider-qualified model (for example, ``ollama/<name>``).
        model_is_priced=is_priced(qualified_model(settings.provider, settings.model)),
        version=__version__,
        data_dir=str(request.app.state.paths.data_dir),
    )


@router.get("/settings")
async def get_settings(request: Request) -> SettingsResponse:
    return await _response(request, await _settings_store(request).get())


def _reject(message: str, field: str | None) -> HTTPException:
    """Build a field-aware 400 response for the form."""
    return HTTPException(status_code=400, detail={"message": message, "field": field})


def _reject_validation(exc: ValidationError) -> HTTPException:
    """Return the first Pydantic error as one line on its field."""
    first = exc.errors()[0]
    location = first.get("loc", ())
    field = str(location[0]) if location else None
    message = str(first.get("msg", "invalid value"))
    # Pydantic prefixes validator ValueErrors with ``Value error, ``.
    return _reject(message.removeprefix("Value error, "), field)


@router.patch("/settings")
async def update_settings(request: Request, body: UpdateSettingsRequest) -> SettingsResponse:
    """Apply a partial settings update; validation failures return field-aware 400s."""
    changes: dict[str, Any] = body.model_dump(exclude_none=True)

    if not changes:
        raise _reject("no settings were supplied", None)

    if "provider" in changes and changes["provider"] not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise _reject(
            f"unknown provider {changes['provider']!r}. Supported: {supported}.", "provider"
        )
    if "provider" in changes and "model" not in changes:
        # The app-wide model only backs a space row that names none. It follows
        # its provider so it cannot name a model from a different provider.
        current = await _settings_store(request).get()
        if changes["provider"] != current.provider:
            changes["model"] = await _new_space_model(
                request,
                changes["provider"],
                changes.get("openai_access", current.openai_access),
            )

    if "channel_space_id" in changes:
        wanted = changes["channel_space_id"].strip()
        if wanted == "":
            changes["channel_space_id"] = None
        else:
            space = await _spaces(request).get(wanted)
            if space is None:
                raise _reject(f"No space with id {wanted!r}.", "channel_space_id")
            if space.archived:
                raise _reject(
                    f"{space.name!r} is archived; a chat command cannot start a run there.",
                    "channel_space_id",
                )

    try:
        updated = await _settings_store(request).update(changes)
    except ValidationError as exc:
        raise _reject_validation(exc) from exc
    except ValueError as exc:
        raise _reject(str(exc), None) from exc

    # The app-wide provider is where a new space starts (migration 016): every
    # space names its own, so changing it moves none of them.

    # Reconcile now: the product has no restart button.
    if changes.keys() & _CHANNEL_SETTINGS:
        channels: ChannelService | None = getattr(request.app.state, "channels", None)
        if channels is not None:
            await channels.reconcile()

    return await _response(request, updated)


class ProviderEntry(BaseModel):
    """Selectable provider."""

    name: str
    requires_key: bool
    #: Whether the model is typed rather than selected (Ollama).
    free_text_model: bool
    #: Default space model, or ``None`` when typed.
    default_model: str | None = None


class ModelEntry(BaseModel):
    """One selectable model: where it sits in the lineup and what it costs."""

    id: str
    tier: Tier
    #: In the provider's current lineup rather than an older model still sold.
    current: bool
    input_micros_per_million: int
    output_micros_per_million: int
    #: Whether the signed-in ChatGPT subscription includes it; ``None`` where
    #: no account limits the provider's models, or its list is not known.
    available: bool | None = None


class ProviderCatalogueResponse(BaseModel):
    """Selectable and priced models by provider."""

    providers: list[ProviderEntry]
    #: Priced models by provider in picker order, current lineup first;
    #: free-text providers have empty lists.
    models: dict[str, list[str]]
    #: The same models with their tier and price.
    catalog: dict[str, list[ModelEntry]]


@router.get("/settings/providers")
async def list_providers(request: Request) -> ProviderCatalogueResponse:
    """List selectable and priced models by provider.

    Dropdowns use this instead of a list that could drift from ``pricing.py``.
    With OpenAI through a ChatGPT subscription, each OpenAI model also says
    whether the plan includes it, so a picker can keep to those.
    """
    settings = await _settings_store(request).get()
    included = await plan_models("openai", settings.openai_access, _chatgpt_runtime(request))
    return ProviderCatalogueResponse(
        providers=[
            ProviderEntry(
                name=name,
                requires_key=secret is not None,
                free_text_model=f"{name}/*" in PRICES,
                default_model=(
                    await _new_space_model(request, name, settings.openai_access)
                    if name == "openai"
                    else default_model_for(name)
                ),
            )
            for name, secret in sorted(SUPPORTED_PROVIDERS.items())
        ],
        models={
            name: [entry.model for entry in catalog_for(name)]
            for name in sorted(SUPPORTED_PROVIDERS)
        },
        catalog={
            name: [
                ModelEntry(
                    id=entry.model,
                    tier=entry.tier,
                    current=entry.current,
                    input_micros_per_million=PRICES[entry.model].input_micros_per_million,
                    output_micros_per_million=PRICES[entry.model].output_micros_per_million,
                    available=(
                        entry.model in included
                        if included is not None and name == "openai"
                        else None
                    ),
                )
                for entry in catalog_for(name)
            ]
            for name in sorted(SUPPORTED_PROVIDERS)
        },
    )


@router.get("/budget")
async def get_budget(request: Request, space_id: str | None = None) -> BudgetResponse:
    """Return month-to-date spend and cap; ``space_id`` adds that space's share."""
    ledger = _ledger(request)
    spent = await ledger.spent_micros()
    cap = await ledger.cap_micros()
    in_space = None if space_id is None else await ledger.spent_micros(space_id=space_id)

    return BudgetResponse(
        period=current_period(),
        spent_micros=spent,
        cap_micros=cap,
        percent_used=(spent * 100 // cap) if cap > 0 else 100,
        spent_display=format_micros(spent),
        cap_display=format_micros(cap),
        space_spent_micros=in_space,
        space_spent_display=None if in_space is None else format_micros(in_space),
    )


@router.get("/usage")
async def get_usage(
    request: Request, period: str | None = None, space_id: str | None = None
) -> UsageReport:
    """Report ledger calls by total, model, space, day, and costly run.

    ``period`` is ``YYYY-MM`` and defaults to this month; ``space_id`` limits
    results to one space. Use the same rows as cap enforcement, so report and
    meter agree.
    """
    chosen = period if period is not None else current_period()
    if len(chosen) != 7 or chosen[4] != "-" or not (chosen[:4] + chosen[5:]).isdigit():
        raise _reject("a period looks like 2026-09", "period")
    usage = UsageStore(request.app.state.db)
    return await usage.report(chosen, space_id, await _ledger(request).cap_micros())


class VerifyResponse(BaseModel):
    """Whether current settings can build a provider, with a failure reason."""

    ok: bool
    #: User-facing failure sentence when ``ok`` is false.
    reason: str | None = None
    #: Built provider and model when ``ok`` is true.
    provider: str | None = None
    model: str | None = None
    #: When the account cannot run the space's model: the closest one it can,
    #: offered, never applied, since the model is never swapped on its own.
    suggested_model: str | None = None


@router.post("/settings/verify")
async def verify_provider(request: Request, space_id: str | None = None) -> VerifyResponse:
    """Check whether settings can build a provider without calling it.

    This dashboard pre-flight shows a run's refusal before Start. ``space_id``
    checks effective space settings.
    """
    settings = await _settings_store(request).get()
    if space_id is not None:
        try:
            space = await _spaces(request).require(space_id)
        except SpaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if space.archived:
            return VerifyResponse(ok=False, reason=SpaceArchivedError(space.name).args[0])
        settings = space.apply_to(settings)

    if settings.provider == "openai" and settings.openai_access == "chatgpt":
        auth = await _chatgpt_runtime(request).status()
        if auth.state != "connected":
            detail = f" {auth.error}" if auth.error else ""
            return VerifyResponse(
                ok=False,
                reason=f"ChatGPT is not signed in. Sign in to ChatGPT in settings.{detail}",
            )
        included = await plan_models(
            settings.provider, settings.openai_access, _chatgpt_runtime(request)
        )
        # A space's own model is what its runs use. The app-wide model only
        # backs a row naming none, so the app-wide check leaves it alone.
        if space_id is not None and included is not None and settings.model not in included:
            closest = equivalent(settings.model, "openai", "openai", included, space=True)
            if closest is None:
                return VerifyResponse(
                    ok=False,
                    reason=(
                        f"Your ChatGPT subscription does not include {settings.model}, and "
                        f"none of the models it does include has a price in this version of "
                        f"AgentBase, so runs through it are refused. Use an OpenAI API key."
                    ),
                )
            return VerifyResponse(
                ok=False,
                reason=(
                    f"Your ChatGPT subscription does not include {settings.model}, so runs "
                    f"in this space would fail. The closest it includes is {closest}; choose "
                    f"it in Space settings. An OpenAI API key reaches every model."
                ),
                suggested_model=closest,
            )

    try:
        provider = build_provider(
            settings,
            _secrets(request),
            chatgpt_runtime=_chatgpt_runtime(request),
        )
    except UnknownProviderError as exc:
        return VerifyResponse(ok=False, reason=str(exc))
    except ProviderAuthError as exc:
        return VerifyResponse(ok=False, reason=str(exc))

    if not is_priced(provider.model):
        return VerifyResponse(
            ok=False,
            reason=(
                f"Model {provider.model!r} has no registered price, so runs using it "
                f"are refused before any API call. Choose a priced model."
            ),
        )

    return VerifyResponse(ok=True, provider=provider.name, model=provider.model)
