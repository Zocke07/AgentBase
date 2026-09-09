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
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agentspace.store.db import Database

__all__ = [
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


class WorkspaceSettings(BaseModel):
    """Everything the user can configure that is not a secret."""

    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    monthly_cap_micros: int = Field(default=DEFAULT_MONTHLY_CAP_MICROS, ge=0)
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL


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
        merged = current.model_copy(update=changes)

        # Re-validate: `model_copy` does not, and a bad value that reaches the
        # table would fail on every subsequent read.
        validated = WorkspaceSettings.model_validate(merged.model_dump())

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
                    (key, json.dumps(getattr(validated, key)), now),
                )

        return validated
