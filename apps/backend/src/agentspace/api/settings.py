"""Settings and budget endpoints.

No endpoint ever returns a key. `configured_secrets` reports *which* names
arrived over stdin; a read-back endpoint would be an exfiltration endpoint for
anything that reaches loopback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentspace import __version__
from agentspace.budget.ledger import current_period
from agentspace.budget.usage import UsageReport, UsageStore
from agentspace.channels.identity import ChannelIdentity
from agentspace.providers.base import ProviderAuthError
from agentspace.providers.chatgpt import ChatGPTRuntime
from agentspace.providers.factory import (
    SUPPORTED_PROVIDERS,
    UnknownProviderError,
    build_provider,
    qualified_model,
)
from agentspace.providers.pricing import MODELS_BY_PROVIDER, PRICES, format_micros, is_priced
from agentspace.secrets import SECRET_KEYS
from agentspace.store.settings import (
    ChannelApprovalPolicy,
    OpenAIAccess,
    WorkspaceSettings,
    default_model_for,
)
from agentspace.store.spaces import SpaceArchivedError, SpaceNotFoundError
from agentspace.tools.catalogue import RiskLevel, ToolPolicy

if TYPE_CHECKING:
    from agentspace.budget.ledger import BudgetLedger
    from agentspace.channels.service import ChannelService
    from agentspace.secrets import SecretStore
    from agentspace.store.settings import SettingsStore
    from agentspace.store.spaces import SpaceStore

__all__ = ["router"]

router = APIRouter()

#: Settings that change which adapters should be connected. Derived from the
#: model rather than hand-listed, so a later channel setting cannot be missed.
_CHANNEL_SETTINGS: frozenset[str] = frozenset(
    name for name in WorkspaceSettings.model_fields if name.startswith("discord_")
)


class SettingsResponse(BaseModel):
    """Workspace settings plus the read-only facts the UI needs beside them."""

    settings: WorkspaceSettings
    #: Which API keys are present. Names only, never values.
    configured_secrets: list[str]
    #: Every secret name the sidecar accepts, present or not, one row each.
    known_secrets: list[str]
    supported_providers: list[str]
    #: False means every run will be refused; the UI says so before Start.
    model_is_priced: bool
    #: The sidecar's release, for the About box. The window is built from the
    #: same version; showing this one says which sidecar actually answered.
    version: str
    #: Where the database and space folders live, for the same box.
    data_dir: str


class UpdateSettingsRequest(BaseModel):
    """A partial update. Every field optional; omitted fields are untouched.

    Unknown fields are rejected, not dropped: Pydantic's default turns a
    misspelled setting into a `200 OK` that changed nothing. This model must
    list every field of :class:`~agentspace.store.settings.WorkspaceSettings`
    (they differ in bounds and optionality, so it cannot be the same class),
    and `test_every_workspace_setting_can_be_patched` keeps the two in step.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = Field(default=None, min_length=1)
    openai_access: OpenAIAccess | None = None
    monthly_cap_micros: int | None = Field(default=None, ge=0)
    ollama_base_url: str | None = Field(default=None, min_length=1)

    # Bounds mirror `WorkspaceSettings`: a limit of zero is not a stricter setting.
    max_steps_per_agent: int | None = Field(default=None, ge=1)
    max_agents_per_run: int | None = Field(default=None, ge=1)
    max_run_seconds: int | None = Field(default=None, ge=1)

    # An empty list is meaningful (it turns pre-authorization off), and
    # `exclude_none` keeps it distinguishable from "not sent".
    auto_approve: list[RiskLevel] | None = None
    #: The whole map replaces the stored one; `{}` clears every per-tool answer.
    tool_policies: dict[str, ToolPolicy] | None = None

    # `channel_identities: []` revokes everyone and must not read as "not sent".
    discord_enabled: bool | None = None
    channel_identities: list[ChannelIdentity] | None = None
    channel_approvals: ChannelApprovalPolicy | None = None

    # Where a chat-started run happens. `exclude_none` means null cannot be
    # sent, so an empty string means "the default space" and is stored as null.
    channel_space_id: str | None = None

    onboarding_completed: bool | None = None


class BudgetResponse(BaseModel):
    period: str
    spent_micros: int
    cap_micros: int
    percent_used: int
    spent_display: str
    cap_display: str
    #: This space's share of the period's spend. The cap is app-wide; there is no per-space cap.
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
        # `qualified_model`, not `settings.model`: the price is looked up
        # under the id the provider namespaces to (`ollama/<name>`).
        model_is_priced=is_priced(qualified_model(settings.provider, settings.model)),
        version=__version__,
        data_dir=str(request.app.state.paths.data_dir),
    )


@router.get("/settings")
async def get_settings(request: Request) -> SettingsResponse:
    return await _response(request, await _settings_store(request).get())


def _reject(message: str, field: str | None) -> HTTPException:
    """A 400 carrying `{message, field}`, so the form can put it on the right input."""
    return HTTPException(status_code=400, detail={"message": message, "field": field})


def _reject_validation(exc: ValidationError) -> HTTPException:
    """The first pydantic error, as one line, on the field it names."""
    first = exc.errors()[0]
    location = first.get("loc", ())
    field = str(location[0]) if location else None
    message = str(first.get("msg", "invalid value"))
    # Pydantic prefixes a `ValueError` raised in a validator with "Value error, ".
    return _reject(message.removeprefix("Value error, "), field)


@router.patch("/settings")
async def update_settings(request: Request, body: UpdateSettingsRequest) -> SettingsResponse:
    """Apply a partial settings update.

    Validation failures are 400s carrying `{message, field}`.
    """
    changes: dict[str, Any] = body.model_dump(exclude_none=True)

    if not changes:
        raise _reject("no settings were supplied", None)

    if "provider" in changes and changes["provider"] not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise _reject(
            f"unknown provider {changes['provider']!r}. Supported: {supported}.", "provider"
        )
    if "provider" in changes and "model" not in changes:
        # The app-wide model is the fallback a space without one inherits, and
        # since spaces name their own it is no longer chosen here: it follows
        # the provider, so it can never name a model of another provider.
        current = await _settings_store(request).get()
        if changes["provider"] != current.provider:
            changes["model"] = default_model_for(changes["provider"]) or ""

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

    # A channel just enabled has to connect now; this product has no restart button.
    if changes.keys() & _CHANNEL_SETTINGS:
        channels: ChannelService | None = getattr(request.app.state, "channels", None)
        if channels is not None:
            await channels.reconcile()

    return await _response(request, updated)


class ProviderEntry(BaseModel):
    """One selectable provider."""

    name: str
    requires_key: bool
    #: True when the model name is typed rather than picked (Ollama).
    free_text_model: bool


class ProviderCatalogueResponse(BaseModel):
    """What can be selected, and which models are priced, per provider."""

    providers: list[ProviderEntry]
    #: Priced models by provider. A free-text provider's list is empty.
    models: dict[str, list[str]]


@router.get("/settings/providers")
async def list_providers() -> ProviderCatalogueResponse:
    """What can be selected, and which models are priced, grouped per provider.

    The dropdowns read this rather than a list that would drift from `pricing.py`.
    """
    return ProviderCatalogueResponse(
        providers=[
            ProviderEntry(
                name=name,
                requires_key=secret is not None,
                free_text_model=f"{name}/*" in PRICES,
            )
            for name, secret in sorted(SUPPORTED_PROVIDERS.items())
        ],
        models={name: MODELS_BY_PROVIDER.get(name, []) for name in sorted(SUPPORTED_PROVIDERS)},
    )


@router.get("/budget")
async def get_budget(request: Request, space_id: str | None = None) -> BudgetResponse:
    """Month-to-date spend against the cap; ``space_id`` adds that space's share beside it."""
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
    """A month of model calls from the ledger: totals, by model, space and day, and the costliest runs.

    ``period`` is ``YYYY-MM`` and defaults to this month; ``space_id`` narrows
    to one space's runs. Read from the same rows the cap is enforced on, so the
    report and the meter cannot disagree.
    """
    chosen = period if period is not None else current_period()
    if len(chosen) != 7 or chosen[4] != "-" or not (chosen[:4] + chosen[5:]).isdigit():
        raise _reject("a period looks like 2026-09", "period")
    usage = UsageStore(request.app.state.db)
    return await usage.report(chosen, space_id, await _ledger(request).cap_micros())


class VerifyResponse(BaseModel):
    """Whether the current settings can build a provider, and why not if not."""

    ok: bool
    #: Set when ``ok`` is false: the sentence to show the user.
    reason: str | None = None
    #: Set when ``ok`` is true: what was built.
    provider: str | None = None
    model: str | None = None


@router.post("/settings/verify")
async def verify_provider(request: Request, space_id: str | None = None) -> VerifyResponse:
    """Check the current settings can build a provider, without calling the model.

    The dashboard's pre-flight: the refusal a run would get, shown before
    Start. With ``space_id`` the space's effective settings are checked.
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
