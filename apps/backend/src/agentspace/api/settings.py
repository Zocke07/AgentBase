"""Settings and budget endpoints.

This is the HTTP face of the Phase 3 acceptance criterion: switching provider
happens here, as data, and nothing downstream changes.

**No endpoint ever returns a key.** :meth:`SecretStore.names` reports *which*
credentials arrived over the stdin handshake so the UI can render "key
configured" — reading one back out is not a capability this API has, because a
read-back endpoint is a key exfiltration endpoint for anything that reaches
loopback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from agentspace.budget.ledger import current_period
from agentspace.channels.identity import ChannelIdentity
from agentspace.providers.base import ProviderAuthError
from agentspace.providers.factory import (
    SUPPORTED_PROVIDERS,
    UnknownProviderError,
    build_provider,
    qualified_model,
)
from agentspace.providers.pricing import PRICES, format_micros, is_priced
from agentspace.store.settings import ChannelApprovalPolicy, WorkspaceSettings
from agentspace.tools.catalogue import RiskLevel

if TYPE_CHECKING:
    from agentspace.budget.ledger import BudgetLedger
    from agentspace.secrets import SecretStore
    from agentspace.store.settings import SettingsStore

__all__ = ["router"]

router = APIRouter()


class SettingsResponse(BaseModel):
    """Workspace settings plus the read-only facts the UI needs beside them."""

    settings: WorkspaceSettings
    #: Which API keys are present. Names only — never values.
    configured_secrets: list[str]
    supported_providers: list[str]
    #: Whether the selected model has a registered price. A false here means
    #: every run will be refused, so the UI can say so before the user tries.
    model_is_priced: bool


class UpdateSettingsRequest(BaseModel):
    """A partial update. Every field optional; omitted fields are untouched.

    **Unknown fields are rejected rather than ignored.** Pydantic's default is
    to drop them, which turns a misspelled or not-yet-supported setting into a
    `200 OK` that changed nothing — the caller is told it worked and it did
    not. That is exactly how the Phase 4 run limits appeared configurable
    through this endpoint for a while without being so.

    **This model must list every field of
    :class:`~agentspace.store.settings.WorkspaceSettings`.** It duplicates that
    list because the two differ in bounds and optionality, and a duplicated
    list is a list that drifts: Phase 6 added `auto_approve` to the settings
    model and not to this one, so `GET /settings` reported a policy that
    `PATCH /settings` refused to set — the workspace's entire approval policy
    was unsettable through the API. `extra="forbid"` made that loud rather than
    silent, which is the Phase 4 fix working, and
    `test_every_workspace_setting_can_be_patched` is what stops the next field
    repeating it.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str | None = None
    model: str | None = Field(default=None, min_length=1)
    monthly_cap_micros: int | None = Field(default=None, ge=0)
    ollama_base_url: str | None = Field(default=None, min_length=1)

    # §5 Phase 4: "All configurable". Bounds mirror `WorkspaceSettings`, where
    # a limit of zero is a run that cannot do anything rather than a stricter
    # setting.
    max_steps_per_agent: int | None = Field(default=None, ge=1)
    max_agents_per_run: int | None = Field(default=None, ge=1)
    max_run_seconds: int | None = Field(default=None, ge=1)

    # §5 Phase 6's policy for unattended operation. An empty list is meaningful
    # here — it is how a user turns pre-authorization back off — and
    # `exclude_none` keeps it distinguishable from "not sent".
    auto_approve: list[RiskLevel] | None = None

    # §5 Phase 8's channels. `channel_identities` has the same empty-list-is-
    # meaningful property as `auto_approve`: sending `[]` is how an owner
    # revokes everyone's access, and it must not be read as "not sent".
    discord_enabled: bool | None = None
    telegram_enabled: bool | None = None
    channel_identities: list[ChannelIdentity] | None = None
    channel_approvals: ChannelApprovalPolicy | None = None


class BudgetResponse(BaseModel):
    period: str
    spent_micros: int
    cap_micros: int
    percent_used: int
    spent_display: str
    cap_display: str


def _settings_store(request: Request) -> SettingsStore:
    store: SettingsStore = request.app.state.settings
    return store


def _secrets(request: Request) -> SecretStore:
    secrets: SecretStore = request.app.state.secrets
    return secrets


def _ledger(request: Request) -> BudgetLedger:
    ledger: BudgetLedger = request.app.state.ledger
    return ledger


async def _response(request: Request, settings: WorkspaceSettings) -> SettingsResponse:
    return SettingsResponse(
        settings=settings,
        configured_secrets=list(_secrets(request).names),
        supported_providers=sorted(SUPPORTED_PROVIDERS),
        # `qualified_model`, not `settings.model`: a provider may namespace
        # what it was given, and the price is looked up under the namespaced
        # id. Asking about the raw value told every Ollama user their runs
        # would be refused when they would in fact have cost nothing.
        model_is_priced=is_priced(qualified_model(settings.provider, settings.model)),
    )


@router.get("/settings")
async def get_settings(request: Request) -> SettingsResponse:
    return await _response(request, await _settings_store(request).get())


@router.patch("/settings")
async def update_settings(request: Request, body: UpdateSettingsRequest) -> SettingsResponse:
    """Apply a partial settings update.

    Validation failures are 400s with a readable message rather than 500s: this
    endpoint backs a form, and Phase 7 surfaces the message inline on the
    offending field.
    """
    changes: dict[str, Any] = body.model_dump(exclude_none=True)

    if not changes:
        raise HTTPException(status_code=400, detail="no settings were supplied")

    if "provider" in changes and changes["provider"] not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider {changes['provider']!r}. Supported: {supported}.",
        )

    try:
        updated = await _settings_store(request).update(changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _response(request, updated)


@router.get("/settings/providers")
async def list_providers() -> dict[str, Any]:
    """What can be selected, and which models are priced.

    Phase 7's dropdowns read this instead of hardcoding a list that would drift
    from `pricing.py` the first time a model is added.
    """
    return {
        "providers": [
            {"name": name, "requires_key": secret is not None}
            for name, secret in sorted(SUPPORTED_PROVIDERS.items())
        ],
        "models": sorted(model for model in PRICES if not model.endswith("/*")),
    }


@router.get("/budget")
async def get_budget(request: Request) -> BudgetResponse:
    """Month-to-date spend against the cap. Phase 7's budget meter reads this."""
    ledger = _ledger(request)
    spent = await ledger.spent_micros()
    cap = await ledger.cap_micros()

    return BudgetResponse(
        period=current_period(),
        spent_micros=spent,
        cap_micros=cap,
        percent_used=(spent * 100 // cap) if cap > 0 else 100,
        spent_display=format_micros(spent),
        cap_display=format_micros(cap),
    )


@router.post("/settings/verify")
async def verify_provider(request: Request) -> dict[str, Any]:
    """Check the current settings can actually build a provider.

    Deliberately does *not* call the model: that would spend money to answer a
    configuration question, and the budget check exists precisely to stop
    unbudgeted calls. It reports whether the credentials and the provider name
    are sufficient to construct one.
    """
    settings = await _settings_store(request).get()

    try:
        provider = build_provider(settings, _secrets(request))
    except UnknownProviderError as exc:
        return {"ok": False, "reason": str(exc)}
    except ProviderAuthError as exc:
        return {"ok": False, "reason": str(exc)}

    if not is_priced(provider.model):
        return {
            "ok": False,
            "reason": (
                f"Model {provider.model!r} has no registered price, so runs using it "
                f"are refused before any API call. Choose a priced model."
            ),
        }

    return {"ok": True, "provider": provider.name, "model": provider.model}
