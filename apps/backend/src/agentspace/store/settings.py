"""Workspace settings — the thing that makes provider switching a setting.

The Phase 3 acceptance criterion is that "switching provider is a settings
change with no code change". This module is where that change lands.

**No secret is ever stored here.** The `settings` table lives in the same
SQLite file as the event log, which is on disk in the clear. API keys reach the
sidecar over stdin at spawn time and stay in memory (§1 constraint 4). What
lives here is the *choice* of provider and model, the monthly cap, and the
Ollama base URL — all of which are configuration, not credentials.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, Field, field_validator

from agentspace.channels.identity import ChannelIdentity, IdentityDirectory
from agentspace.tools.catalogue import RiskLevel

if TYPE_CHECKING:
    from agentspace.store.db import Database

__all__ = [
    "DEFAULT_AUTO_APPROVE",
    "DEFAULT_CHANNEL_APPROVALS",
    "DEFAULT_MAX_AGENTS_PER_RUN",
    "DEFAULT_MAX_RUN_SECONDS",
    "DEFAULT_MAX_STEPS_PER_AGENT",
    "DEFAULT_MONTHLY_CAP_MICROS",
    "SettingsStore",
    "WorkspaceSettings",
]

#: The default monthly spending cap: $20.00, in micros.
#:
#: A default of "unlimited" would mean the cap only exists for users who go
#: looking for it, which is not what §5 Phase 3 asks for — the ledger is meant
#: to enforce a monthly cap, not to offer one. $20 is high enough not to
#: interrupt ordinary use and low enough that a runaway loop is survivable.
DEFAULT_MONTHLY_CAP_MICROS: Final[int] = 20_000_000

#: Default provider and model for a fresh install.
DEFAULT_PROVIDER: Final[str] = "anthropic"
DEFAULT_MODEL: Final[str] = "claude-opus-5"

#: Where a local Ollama daemon listens. Loopback, like everything else.
DEFAULT_OLLAMA_BASE_URL: Final[str] = "http://127.0.0.1:11434"

#: Which risk levels the workspace pre-authorizes, so a tool call at that level
#: runs without stopping to ask (§5 Phase 6: "A policy setting for unattended
#: operation: pre-authorize a named risk subset so overnight runs can
#: progress").
#:
#: **Empty by default, because §5 Phase 6 says "Default is
#: manual-approve-everything".** That is a stronger default than it first looks:
#: it means a fresh install stops on `read_file`, which is mildly annoying and
#: is the correct trade for a product whose entire safety story is that nothing
#: reaches the disk without the user saying so. A default that pre-approved
#: `low` would be a defensible product decision and a different one from what
#: the spec asks for, so it is the user's to make, not this module's.
DEFAULT_AUTO_APPROVE: Final[tuple[RiskLevel, ...]] = ()

#: The Phase 4 run limits (§5: "all configurable"). They live here rather than
#: as constants in `orchestrator/limits.py` because a limit nobody can change
#: is not configurable, and the `settings` table already exists — so this is a
#: new key, not a migration.
DEFAULT_MAX_STEPS_PER_AGENT: Final[int] = 20
DEFAULT_MAX_AGENTS_PER_RUN: Final[int] = 5
DEFAULT_MAX_RUN_SECONDS: Final[int] = 600

#: Who may answer the approval gate for a run that came from a chat channel.
#:
#: ``dashboard_only`` — the question is *shown* in chat, so a run that has
#: stopped does not look like a crashed bot, but the answer has to be given at
#: the machine the tool call would run on. ``originator`` also lets the person
#: who started the run answer it from the chat client they started it from.
#:
#: **The default is the strict one**, matching §5 Phase 6's "Default is
#: manual-approve-everything" in spirit: an approval is the moment the owner
#: decides whether something touches their disk, their shell or their network,
#: and the default should not move that decision onto a phone in a group chat.
#: Neither value is a privileged path (§1 constraint 5) — both go through
#: :meth:`~agentspace.tools.approval.ApprovalService.resolve`, which is the same
#: method `POST /approvals/{id}` calls. The setting decides who is asked, never
#: whether the gate applies.
ChannelApprovalPolicy = Literal["dashboard_only", "originator"]
DEFAULT_CHANNEL_APPROVALS: Final[ChannelApprovalPolicy] = "dashboard_only"


class WorkspaceSettings(BaseModel):
    """Everything the user can configure that is not a secret."""

    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    monthly_cap_micros: int = Field(default=DEFAULT_MONTHLY_CAP_MICROS, ge=0)
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL

    #: The workspace approval policy. An agent definition's own `auto_approve`
    #: is intersected with this and can only narrow it — see
    #: :func:`agentspace.tools.catalogue.effective_auto_approve` and §5 Phase 5's
    #: security note. Widening is the operation that does not exist.
    auto_approve: list[RiskLevel] = Field(default_factory=lambda: list(DEFAULT_AUTO_APPROVE))

    # Run limits. `ge=1` on each: a limit of zero is not a stricter setting,
    # it is a run that cannot do anything, and it would fail in a way that
    # looks like a bug rather than like a setting.
    max_steps_per_agent: int = Field(default=DEFAULT_MAX_STEPS_PER_AGENT, ge=1)
    max_agents_per_run: int = Field(default=DEFAULT_MAX_AGENTS_PER_RUN, ge=1)
    max_run_seconds: int = Field(default=DEFAULT_MAX_RUN_SECONDS, ge=1)

    # --- channels (§5 Phase 8) ------------------------------------------------
    #
    # This is the `settings` table earning the shape it was given in Phase 2.
    # The note recorded then was that a key/value table with a JSON value means
    # "Phase 7's settings UI and Phase 8's channel config do not each need a
    # migration that widens a table", and that is exactly what happened: four
    # new settings, one of them a list of objects, and no migration to add
    # them. (Migration 005 exists for the opposite move — removing a channel —
    # because a stored allowlist entry for it would otherwise fail validation
    # on every read.)

    #: Off by default. A channel that connected on a fresh install would put
    #: this workspace on a network the moment a token happened to be present,
    #: which is the opposite of what §1 constraint 3 is protecting.
    discord_enabled: bool = False

    #: Who may address this workspace from a chat channel, and as whom. Empty
    #: means nobody, which is the only safe reading — see
    #: :mod:`agentspace.channels.identity`.
    channel_identities: list[ChannelIdentity] = Field(default_factory=list)

    channel_approvals: ChannelApprovalPolicy = DEFAULT_CHANNEL_APPROVALS

    @field_validator("channel_identities")
    @classmethod
    def _identities_are_unambiguous(
        cls, entries: list[ChannelIdentity]
    ) -> list[ChannelIdentity]:
        """Refuse a duplicate on write rather than shadowing one on read.

        Whichever entry resolution happened to pick, the other would be a rule
        the owner wrote and the product ignored — and an allowlist that quietly
        ignores half of what it was told is the worst kind of security control.
        """
        return IdentityDirectory.validated(entries)


class SettingsStore:
    """Reads and writes :class:`WorkspaceSettings` as rows in `settings`.

    One row per field rather than one row holding the whole object: a partial
    update then cannot clobber a field it did not mean to touch, which matters
    once Phase 7 has a UI with more than one form on screen.
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

        Validation happens by round-tripping through the model, so an invalid
        value is rejected before anything is written rather than persisted and
        then failing on read.
        """
        return await asyncio.to_thread(self._update_sync, changes)

    def _update_sync(self, changes: dict[str, Any]) -> WorkspaceSettings:
        current = self._get_sync()

        # Merge as plain data, then validate once. The obvious version —
        # `current.model_copy(update=changes)` followed by
        # `model_validate(merged.model_dump())` — reaches the same answer and
        # passes through an object that is lying about its own types on the
        # way: `model_copy` does not validate, so a `channel_identities` list
        # arriving from the API as dicts sits in a field annotated
        # `list[ChannelIdentity]` until the round-trip fixes it. Pydantic says
        # so out loud, and a `PydanticSerializationUnexpectedValue` warning in
        # the sidecar's log is indistinguishable at a glance from the kind that
        # precedes real data loss. Merging dicts has no such intermediate.
        merged = current.model_dump()
        merged.update(changes)

        validated = WorkspaceSettings.model_validate(merged)

        # `mode="json"` rather than `getattr`: a setting whose value is a model
        # — `channel_identities` is a list of them — is not JSON-serialisable as
        # a Python object, and reaching for `getattr` would work for every
        # scalar setting and fail the first time a structured one was written.
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
