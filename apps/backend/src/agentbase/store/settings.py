"""Workspace settings: everything the user can configure that is not a secret.

The `settings` table sits on disk in the clear beside the event log, so no
credential is ever stored here; keys reach the sidecar over stdin and stay in
memory (§1 constraint 4).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, Field, field_validator

from agentbase.channels.identity import ChannelIdentity, IdentityDirectory
from agentbase.tools.catalogue import RiskLevel, ToolPolicy, is_registered

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

#: The default monthly spending cap, $20.00 in micros: not "unlimited", so
#: the cap exists without anyone looking for it; low enough that a runaway
#: loop is survivable.
DEFAULT_MONTHLY_CAP_MICROS: Final[int] = 20_000_000

#: Default provider and model for a fresh install.
DEFAULT_PROVIDER: Final[str] = "anthropic"
DEFAULT_MODEL: Final[str] = "claude-opus-5"

#: The model a space starts with on each provider, and the one the app-wide
#: fallback follows when the provider changes. Ollama's is typed by the user,
#: so it has none. Migration 012 carries the same table for existing rows.
DEFAULT_MODELS: Final[dict[str, str | None]] = {
    "anthropic": DEFAULT_MODEL,
    "openai": "gpt-5.5",
    "ollama": None,
}


def default_model_for(provider: str) -> str | None:
    """The model a space on ``provider`` starts with; ``None`` where it must be typed."""
    return DEFAULT_MODELS.get(provider)


#: Which credential transport the OpenAI provider uses. It is app-wide like
#: credentials themselves; spaces and agent definitions still select only a
#: provider and model.
OpenAIAccess = Literal["api_key", "chatgpt"]
DEFAULT_OPENAI_ACCESS: Final[OpenAIAccess] = "api_key"

#: Where a local Ollama daemon listens. Loopback, like everything else.
DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://127.0.0.1:11434"

#: Risk levels the workspace pre-authorizes, so a call at that level runs
#: without asking. Empty by default (§5 Phase 6: manual-approve-everything),
#: which means a fresh install stops on `read_file`; pre-approving `low` is
#: the user's decision to make.
DEFAULT_AUTO_APPROVE: Final[tuple[RiskLevel, ...]] = ()

#: The run limits. Settings rather than constants, because a limit nobody can
#: change is not configurable.
DEFAULT_MAX_STEPS_PER_AGENT: Final[int] = 20
DEFAULT_MAX_AGENTS_PER_RUN: Final[int] = 5
DEFAULT_MAX_RUN_SECONDS: Final[int] = 600
#: The most one run may spend, in micros ($2.00); 0 turns the ceiling off.
#: The monthly cap bounds the month; this bounds the one run that goes wrong.
#: `orchestrator/limits.py` carries the same figure; a test compares them.
DEFAULT_MAX_RUN_COST_MICROS: Final[int] = 2_000_000

#: Who may answer the approval gate for a run that came from a chat channel.
#: ``dashboard_only`` shows the question in chat and takes the answer at the
#: machine the call would run on; ``originator`` also lets the person who
#: started the run answer from chat. Strict by default: an approval decides
#: whether something touches the owner's disk, and that decision should not
#: move onto a phone in a group chat by default. Neither value is a
#: privileged path; the setting decides who is asked, never whether the gate applies.
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
    """Reads and writes :class:`WorkspaceSettings`, one row per field.

    One row per field so a partial update cannot clobber a field it did not touch.
    """

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
        """Apply a partial update and return the full resulting settings.

        Validated through the model before anything is written.
        """
        return await asyncio.to_thread(self._update_sync, changes)

    def _update_sync(self, changes: dict[str, Any]) -> WorkspaceSettings:
        current = self._get_sync()

        # Merge as plain data, then validate once. `model_copy(update=...)`
        # does not validate, so a list of dicts would sit in a field typed
        # `list[ChannelIdentity]` and Pydantic would warn on every write.
        merged = current.model_dump()
        merged.update(changes)

        validated = WorkspaceSettings.model_validate(merged)

        # `mode="json"`: `channel_identities` is a list of models, not JSON as an object.
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
