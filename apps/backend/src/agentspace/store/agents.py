"""Agent definitions — the rows that replace hardcoded agent classes.

§5 Phase 5: "Agents stop being hardcoded Python classes and become editable
data." This module owns the data half of that: the `agent_defs` row as a typed
object, and the CRUD that writes one.

**Validation lives here, not in the API layer.** §5 Phase 5 says invalid writes
must be rejected "at the API layer with a readable message, not a 500", and
that is what happens — :mod:`agentspace.api.agents` maps each error below to a
status code. But the *rule* is enforced at the only place a row can be written,
because a rule that lives in a request handler is a rule the next writer of a
row does not have to obey. Same reasoning as
:class:`~agentspace.budget.ledger.BudgetedProvider`: make the check structural
and there is no second code path to remember.

**Nothing here widens the security model.** A definition carries a
user-authored system prompt and an allowlist of tool names. It cannot name a
tool that does not exist, and its `auto_approve` can only narrow the workspace
policy — see :func:`agentspace.tools.catalogue.effective_auto_approve`. A
definition is a description of an agent, never a grant of privilege.

**A definition belongs to exactly one space** (§5 Phase 11). Its name is
unique within that space's roster — the only place a supervisor ever resolves
one — so two spaces may each have a `writer`. Moving a definition is a
`space_id` change; an in-flight run's roster is a snapshot, so a move mid-run
leaves that run alone. Copying makes a new row with a new id that the user
may delete, whatever the original was.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from agentspace.providers.factory import SUPPORTED_PROVIDERS
from agentspace.store.builtins import BUILTIN_ROLES
from agentspace.store.spaces import DEFAULT_SPACE_ID, SpaceNotFoundError
from agentspace.tools.catalogue import RiskLevel, is_registered, tool_names

if TYPE_CHECKING:
    import sqlite3

    from agentspace.store.db import Database
    from agentspace.store.settings import SettingsStore

__all__ = [
    "DEFAULT_AGENT_MAX_STEPS",
    "NAME_PATTERN",
    "AgentDef",
    "AgentDefStore",
    "AgentNotFoundError",
    "AgentValidationError",
    "BuiltinNotDeletableError",
    "DuplicateAgentNameError",
]

#: What a definition may be called.
#:
#: Narrower than "any text" for one concrete reason: the name is how a model
#: refers to an agent when it calls `spawn_agent`, and how §4 says a handoff
#: names its recipient. A name with spaces, capitals or punctuation is a name a
#: model renders inconsistently, and every inconsistency is a spawn that fails
#: on a typo the user cannot see. Lowercase, digits, `_` and `-` are
#: unambiguous to type back.
#:
#: It must start with a letter so that `register_agent`'s deduplication suffix
#: (`researcher` -> `researcher-2`) stays a legal name, and so a name is never
#: mistaken for a number by a model or a JSON parser.
NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")

#: §4's `agent_defs.max_steps DEFAULT 20`, used when a caller does not say.
#:
#: It is a *ceiling to fall back to*, not a value to assert: it is clamped to
#: the workspace cap before use. Asserting the literal made creating any agent
#: impossible whenever `max_steps_per_agent` was set below 20 — the request
#: was rejected naming `max_steps`, a field the caller had not supplied. Found
#: by lowering the cap on a real sidecar and creating an ordinary agent.
DEFAULT_AGENT_MAX_STEPS: Final[int] = 20


class AgentValidationError(ValueError):
    """A definition was rejected. The message is written to be shown to a user.

    ``field`` names the offending input so §5 Phase 7's editor can surface the
    message inline on that field rather than in a toast that loses which one
    was wrong.
    """

    def __init__(self, message: str, field: str) -> None:
        super().__init__(message)
        self.field = field


class DuplicateAgentNameError(AgentValidationError):
    """`agent_defs.name` is unique per space (§4, §5 Phase 11), and has to be:
    it is the handle a supervisor spawns by."""

    def __init__(self, name: str) -> None:
        super().__init__(f"An agent named {name!r} already exists in this space.", field="name")
        self.name = name


class AgentNotFoundError(LookupError):
    def __init__(self, identifier: str) -> None:
        super().__init__(f"No agent definition with id {identifier!r}.")
        self.identifier = identifier


class BuiltinNotDeletableError(RuntimeError):
    """§5 Phase 5: built-ins are "editable but not deletable"."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name!r} is a built-in agent and cannot be deleted. You can edit it, "
            f"or disable it so it is not offered to the supervisor."
        )
        self.name = name


class AgentDef(BaseModel):
    """One row of `agent_defs` (§4).

    Frozen: a definition handed to a run is a snapshot of what that run started
    with, and a snapshot that can be mutated in place is not one. See
    :mod:`agentspace.orchestrator.registry`.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    #: The space whose roster this definition is on. Never NULL.
    space_id: str
    name: str
    role: str
    system_prompt: str
    #: ``None`` inherits the workspace default (§4). The two are independent: a
    #: definition may pin a model without pinning a provider.
    provider: str | None = None
    model: str | None = None
    #: An allowlist, never a denylist (§5 Phase 5). Empty means this agent can
    #: reason and hand off but touches nothing.
    allowed_tools: tuple[str, ...] = ()
    max_steps: int = Field(default=20, ge=1)
    #: Risk levels this agent would skip the prompt for. Only ever *narrowed*
    #: against the workspace policy — see `tools.catalogue.effective_auto_approve`.
    #: Nothing consumes it until Phase 6 builds the gate.
    auto_approve: tuple[RiskLevel, ...] = ()
    is_builtin: bool = False
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


_SELECT: Final[str] = (
    "SELECT id, space_id, name, role, system_prompt, provider, model, allowed_tools,"
    " max_steps, auto_approve, is_builtin, enabled, created_at, updated_at"
    " FROM agent_defs"
)


def _row_to_def(row: sqlite3.Row) -> AgentDef:
    return AgentDef(
        id=row["id"],
        space_id=row["space_id"],
        name=row["name"],
        role=row["role"],
        system_prompt=row["system_prompt"],
        provider=row["provider"],
        model=row["model"],
        allowed_tools=tuple(json.loads(row["allowed_tools"])),
        max_steps=row["max_steps"],
        auto_approve=tuple(RiskLevel(level) for level in json.loads(row["auto_approve"])),
        is_builtin=bool(row["is_builtin"]),
        enabled=bool(row["enabled"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class AgentDefStore:
    """Reads and writes `agent_defs`, refusing to write an invalid row.

    Holds a :class:`~agentspace.store.settings.SettingsStore` because one
    validation rule — `max_steps` within the global cap — is a fact about
    workspace settings rather than about the definition.
    :class:`~agentspace.budget.ledger.BudgetLedger` takes one for the same kind
    of reason.
    """

    def __init__(self, db: Database, settings: SettingsStore) -> None:
        self._db = db
        self._settings = settings

    # --- reads -------------------------------------------------------------

    async def list_all(self, space_id: str | None = None) -> list[AgentDef]:
        """Every definition, or every definition on one space's roster."""
        return await asyncio.to_thread(self._list_sync, space_id, only_enabled=False)

    async def list_enabled(self, space_id: str = DEFAULT_SPACE_ID) -> list[AgentDef]:
        """The roster a run in ``space_id`` is offered.

        A disabled definition is not deleted, it is simply not something the
        supervisor can spawn — which is what makes disabling a usable answer
        for a built-in the user cannot delete. A definition on another space's
        roster is not offered either: that is what a space *is*.
        """
        return await asyncio.to_thread(self._list_sync, space_id, only_enabled=True)

    def _list_sync(self, space_id: str | None, *, only_enabled: bool) -> list[AgentDef]:
        clauses: list[str] = []
        params: list[Any] = []
        if space_id is not None:
            clauses.append("space_id = ?")
            params.append(space_id)
        if only_enabled:
            clauses.append("enabled = 1")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._db.read() as connection:
            rows = connection.execute(
                f"{_SELECT}{where} ORDER BY name",
                params,
            ).fetchall()
        return [_row_to_def(row) for row in rows]

    async def get(self, definition_id: str) -> AgentDef | None:
        return await asyncio.to_thread(self._get_sync, definition_id)

    def _get_sync(self, definition_id: str) -> AgentDef | None:
        with self._db.read() as connection:
            row = connection.execute(f"{_SELECT} WHERE id = ?", (definition_id,)).fetchone()
        return _row_to_def(row) if row is not None else None

    async def require(self, definition_id: str) -> AgentDef:
        definition = await self.get(definition_id)
        if definition is None:
            raise AgentNotFoundError(definition_id)
        return definition

    # --- writes ------------------------------------------------------------

    async def create(self, fields: dict[str, Any]) -> AgentDef:
        """Validate and insert a definition.

        :raises AgentValidationError: for any rejected field, including a
            duplicate name.
        """
        cap = (await self._settings.get()).max_steps_per_agent
        return await asyncio.to_thread(self._create_sync, fields, cap)

    def _create_sync(self, fields: dict[str, Any], cap: int) -> AgentDef:
        space_id = _validated_space_id(fields.get("space_id"))
        name = _validated_name(fields.get("name"))
        role = _validated_text(fields.get("role"), field="role", label="role")
        prompt = _validated_text(
            fields.get("system_prompt"), field="system_prompt", label="system prompt"
        )
        tools = _validated_tools(fields.get("allowed_tools") or ())
        steps = _validated_max_steps(_requested_max_steps(fields.get("max_steps"), cap), cap)
        approve = _validated_auto_approve(fields.get("auto_approve") or ())
        provider = _validated_provider(fields.get("provider"))
        model = _optional_text(fields.get("model"))

        with self._db.write() as connection:
            _require_space(connection, space_id)
            if _name_taken(connection, name, space_id, excluding=None):
                raise DuplicateAgentNameError(name)
            definition_id = _insert(
                connection,
                space_id=space_id,
                name=name,
                role=role,
                system_prompt=prompt,
                provider=provider,
                model=model,
                allowed_tools=tools,
                max_steps=steps,
                auto_approve=tuple(str(level) for level in approve),
                enabled=bool(fields.get("enabled", True)),
            )
            row = connection.execute(f"{_SELECT} WHERE id = ?", (definition_id,)).fetchone()

        return _row_to_def(row)

    async def seed_builtins(self, space_id: str) -> list[AgentDef]:
        """Fresh copies of the three seeded roles, on ``space_id``'s roster.

        What a new space asks for with ``seed: "builtins"``. Copies, not the
        built-ins: `is_builtin` stays 0, so the user may delete them.
        """
        return await asyncio.to_thread(self._seed_builtins_sync, space_id)

    def _seed_builtins_sync(self, space_id: str) -> list[AgentDef]:
        with self._db.write() as connection:
            _require_space(connection, space_id)
            ids = [
                _insert(
                    connection,
                    space_id=space_id,
                    name=role["name"],
                    role=role["role"],
                    system_prompt=role["system_prompt"],
                    provider=None,
                    model=None,
                    allowed_tools=role["allowed_tools"],
                    max_steps=DEFAULT_AGENT_MAX_STEPS,
                    auto_approve=(),
                    enabled=True,
                )
                for role in BUILTIN_ROLES
                if not _name_taken(connection, role["name"], space_id, excluding=None)
            ]
            rows = [
                connection.execute(f"{_SELECT} WHERE id = ?", (definition_id,)).fetchone()
                for definition_id in ids
            ]
        return [_row_to_def(row) for row in rows]

    async def copy_roster(self, from_space_id: str, to_space_id: str) -> list[AgentDef]:
        """Copies of every definition on one roster, onto another.

        What a new space asks for with ``seed: {"copy_from": ...}``. Each copy
        is a new row with a new id and `is_builtin = 0`.
        """
        return await asyncio.to_thread(self._copy_roster_sync, from_space_id, to_space_id)

    def _copy_roster_sync(self, from_space_id: str, to_space_id: str) -> list[AgentDef]:
        with self._db.write() as connection:
            _require_space(connection, from_space_id)
            _require_space(connection, to_space_id)
            sources = connection.execute(
                f"{_SELECT} WHERE space_id = ? ORDER BY name", (from_space_id,)
            ).fetchall()
            ids = [
                _copy_row(connection, _row_to_def(source), to_space_id)
                for source in sources
                if not _name_taken(connection, source["name"], to_space_id, excluding=None)
            ]
            rows = [
                connection.execute(f"{_SELECT} WHERE id = ?", (definition_id,)).fetchone()
                for definition_id in ids
            ]
        return [_row_to_def(row) for row in rows]

    async def copy(self, definition_id: str, to_space_id: str) -> AgentDef:
        """A copy of one definition on another space's roster."""
        return await asyncio.to_thread(self._copy_sync, definition_id, to_space_id)

    def _copy_sync(self, definition_id: str, to_space_id: str) -> AgentDef:
        with self._db.write() as connection:
            source = connection.execute(f"{_SELECT} WHERE id = ?", (definition_id,)).fetchone()
            if source is None:
                raise AgentNotFoundError(definition_id)
            _require_space(connection, to_space_id)
            if _name_taken(connection, source["name"], to_space_id, excluding=None):
                raise DuplicateAgentNameError(source["name"])
            new_id = _copy_row(connection, _row_to_def(source), to_space_id)
            row = connection.execute(f"{_SELECT} WHERE id = ?", (new_id,)).fetchone()
        return _row_to_def(row)

    async def update(self, definition_id: str, changes: dict[str, Any]) -> AgentDef:
        """Apply a partial update.

        A built-in is editable — §5 Phase 5 guards only the delete path — so
        `is_builtin` is not consulted here. It is also not *settable*: a user
        cannot promote their own definition into an undeletable one.
        """
        cap = (await self._settings.get()).max_steps_per_agent
        return await asyncio.to_thread(self._update_sync, definition_id, changes, cap)

    def _update_sync(self, definition_id: str, changes: dict[str, Any], cap: int) -> AgentDef:
        columns: dict[str, Any] = {}

        if "name" in changes:
            columns["name"] = _validated_name(changes["name"])
        if "role" in changes:
            columns["role"] = _validated_text(changes["role"], field="role", label="role")
        if "system_prompt" in changes:
            columns["system_prompt"] = _validated_text(
                changes["system_prompt"], field="system_prompt", label="system prompt"
            )
        if "allowed_tools" in changes:
            columns["allowed_tools"] = json.dumps(
                list(_validated_tools(changes["allowed_tools"] or ()))
            )
        if "max_steps" in changes:
            columns["max_steps"] = _validated_max_steps(
                _requested_max_steps(changes["max_steps"], cap), cap
            )
        if "auto_approve" in changes:
            columns["auto_approve"] = json.dumps(
                [str(level) for level in _validated_auto_approve(changes["auto_approve"] or ())]
            )
        if "provider" in changes:
            columns["provider"] = _validated_provider(changes["provider"])
        if "model" in changes:
            columns["model"] = _optional_text(changes["model"])
        if "enabled" in changes:
            columns["enabled"] = int(bool(changes["enabled"]))
        if "space_id" in changes:
            # A move. The in-flight run's roster is a snapshot, so this leaves
            # that run alone; the next run in either space sees the new roster.
            columns["space_id"] = _validated_space_id(changes["space_id"])

        with self._db.write() as connection:
            existing = connection.execute(
                "SELECT name, space_id FROM agent_defs WHERE id = ?", (definition_id,)
            ).fetchone()
            if existing is None:
                raise AgentNotFoundError(definition_id)

            target_space = columns.get("space_id", existing["space_id"])
            if "space_id" in columns:
                _require_space(connection, target_space)
            target_name = columns.get("name", existing["name"])
            if ("name" in columns or "space_id" in columns) and _name_taken(
                connection, target_name, target_space, excluding=definition_id
            ):
                raise DuplicateAgentNameError(target_name)

            if columns:
                columns["updated_at"] = datetime.now(UTC).isoformat()
                assignments = ", ".join(f"{column} = ?" for column in columns)
                connection.execute(
                    f"UPDATE agent_defs SET {assignments} WHERE id = ?",  # noqa: S608
                    (*columns.values(), definition_id),
                )

            row = connection.execute(f"{_SELECT} WHERE id = ?", (definition_id,)).fetchone()

        return _row_to_def(row)

    async def delete(self, definition_id: str) -> None:
        """Delete a definition.

        :raises BuiltinNotDeletableError: for a seeded built-in. §5 Phase 5:
            `is_builtin = 1` guards the delete path *only*.
        """
        await asyncio.to_thread(self._delete_sync, definition_id)

    def _delete_sync(self, definition_id: str) -> None:
        with self._db.write() as connection:
            row = connection.execute(
                "SELECT name, is_builtin FROM agent_defs WHERE id = ?", (definition_id,)
            ).fetchone()
            if row is None:
                raise AgentNotFoundError(definition_id)
            if row["is_builtin"]:
                raise BuiltinNotDeletableError(row["name"])
            connection.execute("DELETE FROM agent_defs WHERE id = ?", (definition_id,))


# --- writing rows ---------------------------------------------------------------


def _insert(
    connection: sqlite3.Connection,
    *,
    space_id: str,
    name: str,
    role: str,
    system_prompt: str,
    provider: str | None,
    model: str | None,
    allowed_tools: Iterable[str],
    max_steps: int,
    auto_approve: Iterable[str],
    enabled: bool,
) -> str:
    """One validated row, inside the caller's transaction. Returns its new id."""
    now = datetime.now(UTC).isoformat()
    definition_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO agent_defs (id, space_id, name, role, system_prompt, provider,"
        " model, allowed_tools, max_steps, auto_approve, is_builtin,"
        " enabled, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
        (
            definition_id,
            space_id,
            name,
            role,
            system_prompt,
            provider,
            model,
            json.dumps(list(allowed_tools)),
            max_steps,
            json.dumps(list(auto_approve)),
            int(enabled),
            now,
            now,
        ),
    )
    return definition_id


def _copy_row(connection: sqlite3.Connection, source: AgentDef, to_space_id: str) -> str:
    return _insert(
        connection,
        space_id=to_space_id,
        name=source.name,
        role=source.role,
        system_prompt=source.system_prompt,
        provider=source.provider,
        model=source.model,
        allowed_tools=source.allowed_tools,
        max_steps=source.max_steps,
        auto_approve=tuple(str(level) for level in source.auto_approve),
        enabled=source.enabled,
    )


# --- validation --------------------------------------------------------------


def _name_taken(
    connection: sqlite3.Connection, name: str, space_id: str, *, excluding: str | None
) -> bool:
    """Check uniqueness within a space, inside the writing transaction.

    Inside, not before: `BEGIN IMMEDIATE` is what makes "no row has this name"
    still true at the moment of the INSERT. The UNIQUE constraint is the real
    guarantee; this exists to turn its `IntegrityError` into a message naming
    the field, which is what §5 Phase 5 asks for and what Phase 7 renders.
    """
    row = connection.execute(
        "SELECT id FROM agent_defs WHERE space_id = ? AND name = ?", (space_id, name)
    ).fetchone()
    return row is not None and row["id"] != excluding


def _require_space(connection: sqlite3.Connection, space_id: str) -> None:
    """A definition cannot be put on a roster that does not exist."""
    row = connection.execute("SELECT id FROM spaces WHERE id = ?", (space_id,)).fetchone()
    if row is None:
        raise SpaceNotFoundError(space_id)


def _validated_space_id(value: Any) -> str:
    """Omitted means the default space, which keeps every caller that predates
    spaces working; blank is an error rather than a guess."""
    if value is None:
        return DEFAULT_SPACE_ID
    text = str(value).strip()
    if not text:
        raise AgentValidationError("An agent belongs to a space.", field="space_id")
    return text


def _validated_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentValidationError("An agent needs a name.", field="name")

    name = value.strip()
    if not NAME_PATTERN.match(name):
        raise AgentValidationError(
            f"{name!r} is not a usable agent name. Use lowercase letters, digits, "
            f"'-' and '_', starting with a letter, up to 40 characters — a "
            f"supervisor has to type this name back exactly to spawn the agent.",
            field="name",
        )
    return name


def _validated_text(value: Any, *, field: str, label: str) -> str:
    """§5 Phase 5 names "non-empty system prompt"; a role is shown in the UI
    beside it and is equally useless empty."""
    if not isinstance(value, str) or not value.strip():
        raise AgentValidationError(f"An agent needs a {label}.", field=field)
    return value.strip()


def _optional_text(value: Any) -> str | None:
    """``None`` and blank both mean "inherit the workspace default" (§4).

    Collapsing the two matters because a cleared form field arrives as `""`,
    and a stored `""` is not a provider name — it is a definition that fails to
    build a provider at spawn time, long after the user could connect the two.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validated_provider(value: Any) -> str | None:
    """A pinned provider must be one that exists (§4: NULL inherits the default).

    Checked on write so the message arrives while the user is looking at the
    form. It is not the only check — `ProviderPool` raises on an unknown name
    too — because a column validated only on write stops being trustworthy the
    day a provider is removed from the registry.
    """
    provider = _optional_text(value)
    if provider is not None and provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise AgentValidationError(
            f"unknown provider {provider!r}. Supported providers are: {supported}. "
            f"Leave it blank to use the workspace default.",
            field="provider",
        )
    return provider


def _validated_tools(value: Any) -> tuple[str, ...]:
    """§5 Phase 5: "every entry in `allowed_tools` must resolve to a registered
    tool"."""
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise AgentValidationError(
            "allowed_tools must be a list of tool names.", field="allowed_tools"
        )

    tools: list[str] = []
    for entry in value:
        name = str(entry).strip()
        if not is_registered(name):
            known = ", ".join(tool_names())
            raise AgentValidationError(
                f"{name!r} is not a tool. Available tools: {known}.",
                field="allowed_tools",
            )
        if name not in tools:
            tools.append(name)
    return tuple(tools)


def _requested_max_steps(value: Any, cap: int) -> Any:
    """Resolve an unsupplied `max_steps` against what this workspace allows."""
    if value is None:
        return min(DEFAULT_AGENT_MAX_STEPS, cap)
    return value


def _validated_max_steps(value: Any, cap: int) -> int:
    """§5 Phase 5: "`max_steps` within the global cap".

    Rejecting here is a courtesy, not the enforcement: the cap is a *setting*
    and can be lowered after this row was written, so
    :mod:`agentspace.orchestrator.registry` clamps again at spawn time. A rule
    checked only on write stops holding the moment the thing it depends on
    changes.
    """
    if isinstance(value, bool):
        raise AgentValidationError("max_steps must be a whole number.", field="max_steps")

    try:
        steps = int(value)
    except (TypeError, ValueError):
        raise AgentValidationError(
            "max_steps must be a whole number.", field="max_steps"
        ) from None

    if steps < 1:
        raise AgentValidationError(
            "max_steps must be at least 1 — an agent with no steps cannot do anything.",
            field="max_steps",
        )
    if steps > cap:
        raise AgentValidationError(
            f"max_steps of {steps} is above this workspace's limit of {cap}. "
            f"Raise 'max steps per agent' in settings first.",
            field="max_steps",
        )
    return steps


def _validated_auto_approve(value: Any) -> tuple[RiskLevel, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise AgentValidationError(
            "auto_approve must be a list of risk levels.", field="auto_approve"
        )

    levels: list[RiskLevel] = []
    for entry in value:
        try:
            level = RiskLevel(str(entry).strip())
        except ValueError:
            known = ", ".join(str(item) for item in RiskLevel)
            raise AgentValidationError(
                f"{entry!r} is not a risk level. Valid levels: {known}.",
                field="auto_approve",
            ) from None
        if level not in levels:
            levels.append(level)
    return tuple(levels)
