"""Spaces: the container a run happens in (§5 Phase 11).

A space owns a roster, a folder and rules; keys, the monthly cap and the
Discord connection stay app-wide. The folder is derived from the id, never
stored, so no row can name a path outside what the application owns. Rules
resolve in layers through :meth:`Space.apply_to`: model and limits override,
``auto_approve`` only narrows, and NULL means inherit. The default space
cannot be archived or deleted (a run whose space was not named lands there),
and a space with runs can be archived but not deleted.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from agentspace.providers.factory import SUPPORTED_PROVIDERS
from agentspace.tools.catalogue import (
    RiskLevel,
    ToolPolicy,
    effective_auto_approve,
    effective_tool_policies,
    is_registered,
)

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from agentspace.store.db import Database
    from agentspace.store.settings import WorkspaceSettings

__all__ = [
    "DEFAULT_SPACE_ID",
    "DEFAULT_SPACE_NAME",
    "DefaultSpaceProtectedError",
    "DuplicateSpaceNameError",
    "Space",
    "SpaceArchivedError",
    "SpaceHasRunsError",
    "SpaceNotFoundError",
    "SpaceStore",
    "SpaceValidationError",
]

#: The space migration 006 creates and backfills into; a literal the migration shares.
DEFAULT_SPACE_ID: Final[str] = "5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00"
DEFAULT_SPACE_NAME: Final[str] = "Main"

#: What a space may be called: anything non-empty that fits in a switcher.
MAX_NAME_LENGTH: Final[int] = 60


class SpaceValidationError(ValueError):
    """A space was rejected. The message is written to be shown to a user."""

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


class DuplicateSpaceNameError(SpaceValidationError):
    def __init__(self, name: str) -> None:
        super().__init__(f"A space named {name!r} already exists.", field="name")
        self.name = name


class SpaceNotFoundError(LookupError):
    def __init__(self, identifier: str) -> None:
        super().__init__(f"No space with id {identifier!r}.")
        self.identifier = identifier


class SpaceArchivedError(RuntimeError):
    """An archived space keeps its runs viewable and starts no new ones."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name!r} is archived. Unarchive it in its settings to start a run there."
        )
        self.name = name


class DefaultSpaceProtectedError(RuntimeError):
    def __init__(self, action: str) -> None:
        super().__init__(
            f"The default space cannot be {action}: a run whose space is not named lands here."
        )


class SpaceHasRunsError(RuntimeError):
    def __init__(self, name: str, runs: int) -> None:
        super().__init__(
            f"{name!r} has {runs} run{'' if runs == 1 else 's'} and cannot be deleted: "
            f"runs are history. Archive it instead."
        )
        self.name = name
        self.runs = runs


class Space(BaseModel):
    """One row of `spaces`. Frozen, like every definition a run reads."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    description: str = ""
    #: ``None`` inherits the app-wide default. The two are independent.
    provider: str | None = None
    model: str | None = None
    #: ``None`` inherits the app-wide policy; a list narrows it.
    auto_approve: tuple[RiskLevel, ...] | None = None
    #: ``None`` inherits the app-wide per-tool answers; a map makes them stricter.
    tool_policies: dict[str, ToolPolicy] | None = None
    max_steps_per_agent: int | None = Field(default=None, ge=1)
    max_agents_per_run: int | None = Field(default=None, ge=1)
    max_run_seconds: int | None = Field(default=None, ge=1)
    #: ``None`` inherits; 0 lifts the per-run cost ceiling for this space.
    max_run_cost_micros: int | None = Field(default=None, ge=0)
    archived: bool = False
    created_at: datetime
    updated_at: datetime

    def apply_to(self, workspace: WorkspaceSettings) -> WorkspaceSettings:
        """The app-wide settings with this space's overrides laid over them.

        Model and limits replace; ``auto_approve`` intersects through
        :func:`~agentspace.tools.catalogue.effective_auto_approve`, so a
        space can never grant a level the app-wide policy has not enabled.
        """
        changes: dict[str, Any] = {}
        if self.provider is not None:
            changes["provider"] = self.provider
        if self.model is not None:
            changes["model"] = self.model
        if self.auto_approve is not None:
            changes["auto_approve"] = list(
                effective_auto_approve(self.auto_approve, tuple(workspace.auto_approve))
            )
        if self.tool_policies is not None:
            changes["tool_policies"] = effective_tool_policies(
                self.tool_policies, workspace.tool_policies
            )
        for limit in _LIMITS:
            value = getattr(self, limit)
            if value is not None:
                changes[limit] = value
        if not changes:
            return workspace
        return workspace.model_validate({**workspace.model_dump(), **changes})

    def as_payload(self) -> dict[str, Any]:
        """What `run.started` records: enough for a replay to name the space."""
        return {"id": self.id, "name": self.name}


_SELECT: Final[str] = (
    "SELECT id, name, description, provider, model, auto_approve, tool_policies,"
    " max_steps_per_agent, max_agents_per_run, max_run_seconds, max_run_cost_micros,"
    " archived, created_at, updated_at FROM spaces"
)

_LIMITS: Final[tuple[str, ...]] = (
    "max_steps_per_agent",
    "max_agents_per_run",
    "max_run_seconds",
    "max_run_cost_micros",
)

#: Limits that may be 0, meaning "no ceiling", rather than at least 1.
_ZERO_MEANS_OFF: Final[frozenset[str]] = frozenset({"max_run_cost_micros"})


def _row_to_space(row: sqlite3.Row) -> Space:
    approve = row["auto_approve"]
    policies = row["tool_policies"]
    return Space(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        provider=row["provider"],
        model=row["model"],
        auto_approve=(
            None
            if approve is None
            else tuple(RiskLevel(level) for level in json.loads(approve))
        ),
        tool_policies=(
            None
            if policies is None
            else {name: ToolPolicy(policy) for name, policy in json.loads(policies).items()}
        ),
        max_steps_per_agent=row["max_steps_per_agent"],
        max_agents_per_run=row["max_agents_per_run"],
        max_run_seconds=row["max_run_seconds"],
        max_run_cost_micros=row["max_run_cost_micros"],
        archived=bool(row["archived"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SpaceStore:
    """Reads and writes `spaces`, refusing to write an invalid row.

    Holds `AppPaths.spaces_dir` so it can say where a space's folder is; the
    folder is created on first use, not on insert.
    """

    def __init__(self, db: Database, spaces_dir: Path) -> None:
        self._db = db
        self.spaces_dir = spaces_dir

    # --- folders -----------------------------------------------------------

    def folder_for(self, space_id: str) -> Path:
        """Where a space's runs read and write. Derived from the id, never stored."""
        return self.spaces_dir / space_id

    # --- reads -------------------------------------------------------------

    async def list_all(self, *, include_archived: bool = True) -> list[Space]:
        return await asyncio.to_thread(self._list_sync, include_archived)

    def _list_sync(self, include_archived: bool) -> list[Space]:
        clause = "" if include_archived else " WHERE archived = 0"
        with self._db.read() as connection:
            rows = connection.execute(
                # The default space first, then by name.
                f"{_SELECT}{clause} ORDER BY (id = ?) DESC, name COLLATE NOCASE",
                (DEFAULT_SPACE_ID,),
            ).fetchall()
        return [_row_to_space(row) for row in rows]

    async def get(self, space_id: str) -> Space | None:
        return await asyncio.to_thread(self._get_sync, space_id)

    def _get_sync(self, space_id: str) -> Space | None:
        with self._db.read() as connection:
            row = connection.execute(f"{_SELECT} WHERE id = ?", (space_id,)).fetchone()
        return _row_to_space(row) if row is not None else None

    async def require(self, space_id: str) -> Space:
        space = await self.get(space_id)
        if space is None:
            raise SpaceNotFoundError(space_id)
        return space

    # --- writes ------------------------------------------------------------

    async def create(self, fields: dict[str, Any]) -> Space:
        """Validate and insert a space. Seeding the roster is the agent store's job."""
        return await asyncio.to_thread(self._create_sync, fields)

    def _create_sync(self, fields: dict[str, Any]) -> Space:
        columns = _validated_columns(fields, creating=True)
        now = datetime.now(UTC).isoformat()
        space_id = str(uuid.uuid4())

        with self._db.write() as connection:
            if _name_taken(connection, columns["name"], excluding=None):
                raise DuplicateSpaceNameError(columns["name"])
            keys = ["id", *columns, "created_at", "updated_at"]
            placeholders = ", ".join("?" for _ in keys)
            connection.execute(
                f"INSERT INTO spaces ({', '.join(keys)}) VALUES ({placeholders})",  # noqa: S608
                (space_id, *columns.values(), now, now),
            )
            row = connection.execute(f"{_SELECT} WHERE id = ?", (space_id,)).fetchone()
        return _row_to_space(row)

    async def update(self, space_id: str, changes: dict[str, Any]) -> Space:
        """Apply a partial update, including archiving and unarchiving."""
        return await asyncio.to_thread(self._update_sync, space_id, changes)

    def _update_sync(self, space_id: str, changes: dict[str, Any]) -> Space:
        columns = _validated_columns(changes, creating=False)

        with self._db.write() as connection:
            existing = connection.execute(
                "SELECT id FROM spaces WHERE id = ?", (space_id,)
            ).fetchone()
            if existing is None:
                raise SpaceNotFoundError(space_id)
            if space_id == DEFAULT_SPACE_ID and columns.get("archived"):
                raise DefaultSpaceProtectedError("archived")
            if "name" in columns and _name_taken(
                connection, columns["name"], excluding=space_id
            ):
                raise DuplicateSpaceNameError(columns["name"])

            if columns:
                columns["updated_at"] = datetime.now(UTC).isoformat()
                assignments = ", ".join(f"{column} = ?" for column in columns)
                connection.execute(
                    f"UPDATE spaces SET {assignments} WHERE id = ?",  # noqa: S608
                    (*columns.values(), space_id),
                )
            row = connection.execute(f"{_SELECT} WHERE id = ?", (space_id,)).fetchone()
        return _row_to_space(row)

    async def delete(self, space_id: str) -> None:
        """Delete a space, its agents and its schedules.

        :raises DefaultSpaceProtectedError: for the default space.
        :raises SpaceHasRunsError: when any run belongs to it; archive instead.
        """
        await asyncio.to_thread(self._delete_sync, space_id)

    def _delete_sync(self, space_id: str) -> None:
        with self._db.write() as connection:
            row = connection.execute(
                "SELECT name FROM spaces WHERE id = ?", (space_id,)
            ).fetchone()
            if row is None:
                raise SpaceNotFoundError(space_id)
            if space_id == DEFAULT_SPACE_ID:
                raise DefaultSpaceProtectedError("deleted")
            runs = connection.execute(
                "SELECT COUNT(*) FROM runs WHERE space_id = ?", (space_id,)
            ).fetchone()[0]
            if runs:
                raise SpaceHasRunsError(row["name"], int(runs))
            connection.execute("DELETE FROM agent_defs WHERE space_id = ?", (space_id,))
            connection.execute("DELETE FROM schedules WHERE space_id = ?", (space_id,))
            connection.execute("DELETE FROM spaces WHERE id = ?", (space_id,))


# --- validation --------------------------------------------------------------


def _name_taken(connection: sqlite3.Connection, name: str, *, excluding: str | None) -> bool:
    row = connection.execute(
        "SELECT id FROM spaces WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    return row is not None and row["id"] != excluding


def _validated_columns(fields: dict[str, Any], *, creating: bool) -> dict[str, Any]:
    """The columns a create or update may write, each checked.

    A key that is absent is left alone; a key that is present and ``None``
    means "inherit" for a rule and is an error for a name.
    """
    columns: dict[str, Any] = {}

    if creating or "name" in fields:
        columns["name"] = _validated_name(fields.get("name"))
    if "description" in fields:
        description = fields["description"]
        columns["description"] = "" if description is None else str(description).strip()
    if "provider" in fields:
        columns["provider"] = _validated_provider(fields["provider"])
    if "model" in fields:
        columns["model"] = _optional_text(fields["model"])
    if "auto_approve" in fields:
        levels = _validated_auto_approve(fields["auto_approve"])
        columns["auto_approve"] = (
            None if levels is None else json.dumps([str(level) for level in levels])
        )
    if "tool_policies" in fields:
        policies = _validated_tool_policies(fields["tool_policies"])
        columns["tool_policies"] = (
            None
            if policies is None
            else json.dumps({name: str(policy) for name, policy in policies.items()})
        )
    for limit in _LIMITS:
        if limit in fields:
            columns[limit] = _validated_limit(fields[limit], limit)
    if "archived" in fields:
        columns["archived"] = int(bool(fields["archived"]))

    return columns


def _validated_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpaceValidationError("A space needs a name.", field="name")
    name = " ".join(value.split())
    if len(name) > MAX_NAME_LENGTH:
        raise SpaceValidationError(
            f"A space's name is at most {MAX_NAME_LENGTH} characters.", field="name"
        )
    return name


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validated_provider(value: Any) -> str | None:
    provider = _optional_text(value)
    if provider is not None and provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise SpaceValidationError(
            f"unknown provider {provider!r}. Supported providers are: {supported}. "
            f"Leave it blank to inherit the app-wide default.",
            field="provider",
        )
    return provider


def _validated_tool_policies(value: Any) -> dict[str, ToolPolicy] | None:
    """A map of tool name to answer, or null to inherit. `ask` entries are dropped:
    a space says nothing about a tool by leaving it out."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SpaceValidationError(
            "tool_policies must map tool names to ask, allow or deny, or be null to inherit.",
            field="tool_policies",
        )
    policies: dict[str, ToolPolicy] = {}
    for name, entry in value.items():
        if not is_registered(str(name)):
            raise SpaceValidationError(f"Unknown tool: {name}.", field="tool_policies")
        try:
            policy = ToolPolicy(str(entry).strip())
        except ValueError:
            raise SpaceValidationError(
                f"{entry!r} is not a tool policy. Valid answers: ask, allow, deny.",
                field="tool_policies",
            ) from None
        if policy is not ToolPolicy.ASK:
            policies[str(name)] = policy
    return policies


def _validated_auto_approve(value: Any) -> tuple[RiskLevel, ...] | None:
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise SpaceValidationError(
            "auto_approve must be a list of risk levels, or null to inherit.",
            field="auto_approve",
        )
    levels: list[RiskLevel] = []
    for entry in value:
        try:
            level = RiskLevel(str(entry).strip())
        except ValueError:
            known = ", ".join(str(item) for item in RiskLevel)
            raise SpaceValidationError(
                f"{entry!r} is not a risk level. Valid levels: {known}.",
                field="auto_approve",
            ) from None
        if level not in levels:
            levels.append(level)
    return tuple(levels)


def _validated_limit(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise SpaceValidationError(f"{field} must be a whole number.", field=field)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise SpaceValidationError(f"{field} must be a whole number.", field=field) from None
    floor = 0 if field in _ZERO_MEANS_OFF else 1
    if number < floor:
        raise SpaceValidationError(
            f"{field} must be at least {floor}, or blank to inherit the app-wide default.",
            field=field,
        )
    return number
