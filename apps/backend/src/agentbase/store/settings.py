"""Non-secret workspace settings.

The on-disk settings table never stores credentials; keys arrive over stdin
and remain in memory (§1 constraint 4).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, Field, field_validator

from agentbase.channels.identity import ChannelIdentity, IdentityDirectory
from agentbase.tools.catalogue import (
    POLICY_LEVELS,
    RiskLevel,
    ToolPolicy,
    is_registered,
    policy_may_allow,
)

if TYPE_CHECKING:
    from agentbase.store.db import Database

__all__ = [
    "DEFAULT_AUTO_APPROVE",
    "DEFAULT_CHANNEL_APPROVALS",
    "DEFAULT_MAX_AGENTS_PER_RUN",
    "DEFAULT_MAX_RUN_COST_MICROS",
    "DEFAULT_MAX_RUN_SECONDS",
    "DEFAULT_MAX_STEPS_PER_AGENT",
    "DEFAULT_MODELS",
    "DEFAULT_MONTHLY_CAP_MICROS",
    "OpenAIAccess",
    "SettingsStore",
    "WorkspaceSettings",
    "default_model_for",
]

#: Default monthly cap: $20.00 in micros.
DEFAULT_MONTHLY_CAP_MICROS: Final[int] = 20_000_000

#: Default provider and model for a fresh install. The app-wide provider is
#: only where a new space starts; each space names its own provider and model.
DEFAULT_PROVIDER: Final[str] = "anthropic"
DEFAULT_MODEL: Final[str] = "claude-opus-5-5"

#: Provider defaults for new spaces: each provider's current model at
#: `catalog.DEFAULT_TIER`, which a test holds them to. Ollama's are typed.
DEFAULT_MODELS: Final[dict[str, str | None]] = {
    "anthropic": DEFAULT_MODEL,
    "openai": "gpt-6-sol",
    "ollama": None,
}


def default_model_for(provider: str) -> str | None:
    """The model a new space on ``provider`` starts with; ``None`` where it must be typed."""
    return DEFAULT_MODELS.get(provider)


#: App-wide OpenAI credential transport; spaces still select provider and model.
OpenAIAccess = Literal["api_key", "chatgpt"]
DEFAULT_OPENAI_ACCESS: Final[OpenAIAccess] = "api_key"

#: Where a local Ollama daemon listens. Loopback, like everything else.
DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://127.0.0.1:11434"

#: Pre-authorized risk levels; empty means every tool call asks by default.
DEFAULT_AUTO_APPROVE: Final[tuple[RiskLevel, ...]] = ()

#: Configurable run limits.
DEFAULT_MAX_STEPS_PER_AGENT: Final[int] = 20
DEFAULT_MAX_AGENTS_PER_RUN: Final[int] = 5
DEFAULT_MAX_RUN_SECONDS: Final[int] = 600
#: Per-run $2.00 ceiling in micros; 0 disables it.
DEFAULT_MAX_RUN_COST_MICROS: Final[int] = 2_000_000

#: Chat-run approval responder. ``dashboard_only`` is strict by default;
#: ``originator`` also permits the chat requester to answer.
ChannelApprovalPolicy = Literal["dashboard_only", "originator"]
DEFAULT_CHANNEL_APPROVALS: Final[ChannelApprovalPolicy] = "dashboard_only"


class WorkspaceSettings(BaseModel):
    """Everything the user can configure that is not a secret."""

    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    openai_access: OpenAIAccess = DEFAULT_OPENAI_ACCESS
    monthly_cap_micros: int = Field(default=DEFAULT_MONTHLY_CAP_MICROS, ge=0)
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL

    #: The workspace approval policy. A definition's own `auto_approve` can
    #: only narrow it (:func:`~agentbase.tools.catalogue.effective_auto_approve`).
    auto_approve: list[RiskLevel] = Field(default_factory=lambda: list(DEFAULT_AUTO_APPROVE))

    #: Per-tool answers that come before the risk-level rule: a tool set to
    #: ``allow`` runs without asking, one set to ``deny`` is refused without
    #: asking, and one absent (or ``ask``) is decided by `auto_approve`. A
    #: space can only make these stricter (`effective_tool_policies`).
    tool_policies: dict[str, ToolPolicy] = Field(default_factory=dict)

    # `ge=1`: a limit of zero is a run that cannot do anything, not a stricter setting.
    max_steps_per_agent: int = Field(default=DEFAULT_MAX_STEPS_PER_AGENT, ge=1)
    max_agents_per_run: int = Field(default=DEFAULT_MAX_AGENTS_PER_RUN, ge=1)
    max_run_seconds: int = Field(default=DEFAULT_MAX_RUN_SECONDS, ge=1)
    #: A ceiling on one run's spend, in micros; 0 means none beyond the monthly cap.
    max_run_cost_micros: int = Field(default=DEFAULT_MAX_RUN_COST_MICROS, ge=0)

    # --- channels ---------------------------------------------------------------

    #: Off by default: a channel must not connect the moment a token happens to exist.
    discord_enabled: bool = False

    #: Who may address this workspace from a chat channel, and as whom. Empty means nobody.
    channel_identities: list[ChannelIdentity] = Field(default_factory=list)

    channel_approvals: ChannelApprovalPolicy = DEFAULT_CHANNEL_APPROVALS

    #: Where a chat-started run happens; ``None`` is the default space. The
    #: API checks the space exists; a stored id since deleted falls back at launch.
    channel_space_id: str | None = None

    # --- the window -------------------------------------------------------------

    #: Whether the first-run tour has been finished or skipped. Kept here rather
    #: than in the webview's storage so it survives an upgrade with the rest of
    #: the data and comes back exactly when "start over" deletes that data.
    onboarding_completed: bool = False

    @field_validator("auto_approve")
    @classmethod
    def _auto_approve_leaves_high_risk_to_a_person(
        cls, levels: list[RiskLevel]
    ) -> list[RiskLevel]:
        if any(level not in POLICY_LEVELS for level in levels):
            msg = (
                "high risk calls always ask a person: run_shell runs commands as "
                "you with no isolation, so it cannot be pre-approved."
            )
            raise ValueError(msg)
        return levels

    @field_validator("tool_policies")
    @classmethod
    def _tool_policies_name_real_tools(
        cls, policies: dict[str, ToolPolicy]
    ) -> dict[str, ToolPolicy]:
        """A policy for a tool that does not exist would be a silent no-op."""
        unknown = sorted(name for name in policies if not is_registered(name))
        if unknown:
            msg = f"Unknown tool{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)}."
            raise ValueError(msg)
        refused = sorted(
            name
            for name, policy in policies.items()
            if policy is ToolPolicy.ALLOW and not policy_may_allow(name)
        )
        if refused:
            msg = (
                f"{', '.join(refused)} cannot be set to always allow: it is high "
                f"risk, so a person answers every call to it."
            )
            raise ValueError(msg)
        # `ask` is the absence of an answer; storing it would only clutter the row.
        return {
            name: policy for name, policy in policies.items() if policy is not ToolPolicy.ASK
        }

    @field_validator("channel_identities")
    @classmethod
    def _identities_are_unambiguous(
        cls, entries: list[ChannelIdentity]
    ) -> list[ChannelIdentity]:
        """Refuse a duplicate on write rather than silently shadowing one on read."""
        return IdentityDirectory.validated(entries)


class SettingsStore:
    """Read and write :class:`WorkspaceSettings` one field per row."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self) -> WorkspaceSettings:
        return await asyncio.to_thread(self._get_sync)

    def _get_sync(self) -> WorkspaceSettings:
        with self._db.read() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()

        stored: dict[str, Any] = {}
        for row in rows:
            if row["key"] in WorkspaceSettings.model_fields:
                stored[row["key"]] = json.loads(row["value"])

        return WorkspaceSettings(**stored)

    async def update(self, changes: dict[str, Any]) -> WorkspaceSettings:
        """Validate and apply a partial update, returning complete settings."""
        return await asyncio.to_thread(self._update_sync, changes)

    def _update_sync(self, changes: dict[str, Any]) -> WorkspaceSettings:
        current = self._get_sync()

        # Merge plain data, then validate once; ``model_copy`` skips validation.
        merged = current.model_dump()
        merged.update(changes)

        validated = WorkspaceSettings.model_validate(merged)

        # ``channel_identities`` needs JSON-mode model serialization.
        dumped = validated.model_dump(mode="json")

        now = datetime.now(UTC).isoformat()
        with self._db.write() as connection:
            for key in changes:
                if key not in WorkspaceSettings.model_fields:
                    msg = f"unknown setting {key!r}"
                    raise ValueError(msg)
                connection.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                    " updated_at = excluded.updated_at",
                    (key, json.dumps(dumped[key]), now),
                )

        return validated
