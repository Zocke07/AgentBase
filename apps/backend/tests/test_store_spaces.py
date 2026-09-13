"""Spaces: migration 006, the store, and the layering of rules. Written before
the store existed (§6): the migration rebuilds two referenced tables over a
user's whole history, so the first test upgrades a populated v5 database and
asserts every row survives with a space.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentspace.store import db as db_module
from agentspace.store.db import LATEST_SCHEMA_VERSION, Database
from agentspace.store.settings import WorkspaceSettings
from agentspace.store.spaces import (
    DEFAULT_SPACE_ID,
    DEFAULT_SPACE_NAME,
    DefaultSpaceProtectedError,
    DuplicateSpaceNameError,
    Space,
    SpaceHasRunsError,
    SpaceNotFoundError,
    SpaceStore,
    SpaceValidationError,
)
from agentspace.tools.catalogue import RiskLevel

if TYPE_CHECKING:
    from agentspace.config import AppPaths


def _populate_v5(app_paths: AppPaths) -> None:
    """A v5 database with one of everything, wired together by foreign keys."""
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(m for m in original if m.version <= 5)
    database = Database(app_paths.db_path)
    try:
        database.connect()
        assert database.schema_version == 5
        with database.write() as connection:
            connection.execute(
                "INSERT INTO runs (id, goal, status, origin, created_at, finished_at)"
                " VALUES ('run-a', 'old goal', 'completed', 'ui',"
                " '2026-09-01T00:00:00+00:00', '2026-09-01T00:01:00+00:00')"
            )
            connection.execute(
                "INSERT INTO runs (id, goal, status, origin, origin_ref, created_at)"
                " VALUES ('run-b', 'chat goal', 'failed', 'discord', 'thread-1',"
                " '2026-09-02T00:00:00+00:00')"
            )
            for seq in (1, 2, 3):
                connection.execute(
                    "INSERT INTO events (run_id, seq, agent_id, type, payload, ts)"
                    " VALUES ('run-a', ?, 'supervisor', 'agent.thinking', '{}',"
                    " '2026-09-01T00:00:00+00:00')",
                    (seq,),
                )
            connection.execute(
                "INSERT INTO approvals (id, run_id, tool, args, risk, status, created_at)"
                " VALUES ('ap-1', 'run-a', 'write_file', '{}', 'medium', 'approved',"
                " '2026-09-01T00:00:30+00:00')"
            )
            connection.execute(
                "INSERT INTO spend (run_id, period, provider, model, input_tokens,"
                " output_tokens, cost_micros, ts) VALUES ('run-a', '2026-09', 'ollama',"
                " 'ollama/qwen3:4b', 10, 5, 0, '2026-09-01T00:00:40+00:00')"
            )
            connection.execute(
                "INSERT INTO agent_defs (id, name, role, system_prompt, allowed_tools,"
                " max_steps, is_builtin, enabled, created_at, updated_at)"
                " VALUES ('def-mine', 'poet', 'Writes verse', 'You rhyme.', '[]', 5, 0, 0,"
                " '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')"
            )
    finally:
        database.close()
        db_module.MIGRATIONS = original


def test_a_populated_v5_database_upgrades_with_every_row_in_the_default_space(
    app_paths: AppPaths,
) -> None:
    """§5 Phase 11's third acceptance criterion, minus the folder."""
    _populate_v5(app_paths)

    upgraded = Database(app_paths.db_path)
    upgraded.connect()
    try:
        assert upgraded.schema_version == LATEST_SCHEMA_VERSION >= 6

        with upgraded.read() as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1

            spaces = connection.execute("SELECT id, name, archived FROM spaces").fetchall()
            runs = connection.execute(
                "SELECT id, space_id, goal, status, origin, origin_ref, finished_at"
                " FROM runs ORDER BY id"
            ).fetchall()
            events = connection.execute(
                "SELECT run_id, seq FROM events ORDER BY seq"
            ).fetchall()
            approvals = connection.execute(
                "SELECT id, run_id, status FROM approvals"
            ).fetchall()
            spend = connection.execute("SELECT run_id, cost_micros FROM spend").fetchall()
            defs = connection.execute(
                "SELECT id, space_id, name, is_builtin, enabled FROM agent_defs ORDER BY name"
            ).fetchall()

        assert [tuple(row) for row in spaces] == [(DEFAULT_SPACE_ID, DEFAULT_SPACE_NAME, 0)]
        assert [tuple(row) for row in runs] == [
            (
                "run-a",
                DEFAULT_SPACE_ID,
                "old goal",
                "completed",
                "ui",
                None,
                "2026-09-01T00:01:00+00:00",
            ),
            ("run-b", DEFAULT_SPACE_ID, "chat goal", "failed", "discord", "thread-1", None),
        ]
        assert [tuple(row) for row in events] == [("run-a", 1), ("run-a", 2), ("run-a", 3)]
        assert [tuple(row) for row in approvals] == [("ap-1", "run-a", "approved")]
        assert [tuple(row) for row in spend] == [("run-a", 0)]
        # The three built-ins from 003 and the user's own row, all in the
        # default space, the user's disabled row still disabled.
        assert [
            (row["name"], row["space_id"], row["is_builtin"], row["enabled"]) for row in defs
        ] == [
            ("poet", DEFAULT_SPACE_ID, 0, 0),
            ("researcher", DEFAULT_SPACE_ID, 1, 1),
            ("reviewer", DEFAULT_SPACE_ID, 1, 1),
            ("writer", DEFAULT_SPACE_ID, 1, 1),
        ]
    finally:
        upgraded.close()


def test_the_rebuilt_tables_enforce_their_foreign_keys(db: Database) -> None:
    """A rebuild that quietly dropped the REFERENCES would pass every read."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError), db.write() as connection:
        connection.execute(
            "INSERT INTO runs (id, space_id, goal, status, origin, created_at)"
            " VALUES ('x', 'no-such-space', 'g', 'pending', 'ui', '2026-09-01T00:00:00+00:00')"
        )
    with pytest.raises(sqlite3.IntegrityError), db.write() as connection:
        connection.execute(
            "INSERT INTO events (run_id, seq, type, payload, ts)"
            " VALUES ('no-such-run', 1, 'run.started', '{}', '2026-09-01T00:00:00+00:00')"
        )


def test_the_same_agent_name_may_exist_in_two_spaces(db: Database) -> None:
    """`UNIQUE(name)` became `UNIQUE(space_id, name)`."""
    with db.write() as connection:
        connection.execute(
            "INSERT INTO spaces (id, name, created_at, updated_at)"
            " VALUES ('other', 'Other', '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO agent_defs (id, space_id, name, role, system_prompt, allowed_tools,"
            " created_at, updated_at) VALUES ('w2', 'other', 'writer', 'r', 'p', '[]',"
            " '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')"
        )
    with db.read() as connection:
        writers = connection.execute(
            "SELECT space_id FROM agent_defs WHERE name = 'writer' ORDER BY space_id"
        ).fetchall()
    assert [row["space_id"] for row in writers] == [DEFAULT_SPACE_ID, "other"]


def test_the_migration_names_the_same_default_space_as_the_store() -> None:
    """Two literals that must agree, checked rather than trusted."""
    sixth = next(m for m in db_module.MIGRATIONS if m.version == 6)
    assert sixth.defer_foreign_keys
    assert DEFAULT_SPACE_ID in sixth.sql
    assert f"'{DEFAULT_SPACE_NAME}'" in sixth.sql


# --- the store ----------------------------------------------------------------


@pytest.fixture
def spaces(db: Database, app_paths: AppPaths) -> SpaceStore:
    return SpaceStore(db, app_paths.spaces_dir)


@pytest.mark.anyio
async def test_a_fresh_database_has_the_default_space_and_nothing_else(
    spaces: SpaceStore,
) -> None:
    listed = await spaces.list_all()
    assert [space.name for space in listed] == [DEFAULT_SPACE_NAME]
    assert listed[0].id == DEFAULT_SPACE_ID
    assert listed[0].auto_approve is None
    assert listed[0].max_run_seconds is None


@pytest.mark.anyio
async def test_create_update_and_list(spaces: SpaceStore) -> None:
    created = await spaces.create({"name": "  Research   lab ", "description": "Papers"})
    assert created.name == "Research lab"
    assert created.description == "Papers"
    assert created.id != DEFAULT_SPACE_ID

    updated = await spaces.update(created.id, {"max_run_seconds": 1200, "model": "gpt-5"})
    assert updated.max_run_seconds == 1200
    assert updated.model == "gpt-5"
    assert updated.provider is None

    # Back to inheriting: null, not zero.
    inherited = await spaces.update(created.id, {"max_run_seconds": None})
    assert inherited.max_run_seconds is None

    listed = await spaces.list_all()
    assert [space.name for space in listed] == [DEFAULT_SPACE_NAME, "Research lab"]


@pytest.mark.anyio
async def test_a_duplicate_name_is_refused_case_insensitively(spaces: SpaceStore) -> None:
    await spaces.create({"name": "Lab"})
    with pytest.raises(DuplicateSpaceNameError):
        await spaces.create({"name": "lab"})
    with pytest.raises(DuplicateSpaceNameError):
        await spaces.update(DEFAULT_SPACE_ID, {"name": "LAB"})


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"name": ""}, "name"),
        ({"name": "x" * 61}, "name"),
        ({"name": "ok", "provider": "nope"}, "provider"),
        ({"name": "ok", "auto_approve": ["extreme"]}, "auto_approve"),
        ({"name": "ok", "auto_approve": "low"}, "auto_approve"),
        ({"name": "ok", "max_steps_per_agent": 0}, "max_steps_per_agent"),
        ({"name": "ok", "max_run_seconds": "soon"}, "max_run_seconds"),
        ({"name": "ok", "max_agents_per_run": True}, "max_agents_per_run"),
    ],
)
@pytest.mark.anyio
async def test_invalid_fields_are_refused_naming_the_field(
    spaces: SpaceStore, fields: dict[str, object], field: str
) -> None:
    with pytest.raises(SpaceValidationError) as raised:
        await spaces.create(fields)
    assert raised.value.field == field


@pytest.mark.anyio
async def test_the_default_space_cannot_be_archived_or_deleted(spaces: SpaceStore) -> None:
    with pytest.raises(DefaultSpaceProtectedError):
        await spaces.update(DEFAULT_SPACE_ID, {"archived": True})
    with pytest.raises(DefaultSpaceProtectedError):
        await spaces.delete(DEFAULT_SPACE_ID)
    # Renaming it is fine; it is the identity that is protected, not the label.
    renamed = await spaces.update(DEFAULT_SPACE_ID, {"name": "Home base"})
    assert renamed.name == "Home base"


@pytest.mark.anyio
async def test_a_space_with_runs_can_be_archived_but_not_deleted(
    spaces: SpaceStore, db: Database
) -> None:
    lab = await spaces.create({"name": "Lab"})
    with db.write() as connection:
        connection.execute(
            "INSERT INTO runs (id, space_id, goal, status, origin, created_at)"
            " VALUES ('r', ?, 'g', 'completed', 'ui', '2026-09-01T00:00:00+00:00')",
            (lab.id,),
        )

    with pytest.raises(SpaceHasRunsError):
        await spaces.delete(lab.id)

    archived = await spaces.update(lab.id, {"archived": True})
    assert archived.archived
    assert [s.name for s in await spaces.list_all(include_archived=False)] == [
        DEFAULT_SPACE_NAME
    ]
    assert [s.name for s in await spaces.list_all()] == [DEFAULT_SPACE_NAME, "Lab"]


@pytest.mark.anyio
async def test_deleting_an_empty_space_deletes_its_agents(
    spaces: SpaceStore, db: Database
) -> None:
    lab = await spaces.create({"name": "Lab"})
    with db.write() as connection:
        connection.execute(
            "INSERT INTO agent_defs (id, space_id, name, role, system_prompt, allowed_tools,"
            " created_at, updated_at) VALUES ('a', ?, 'writer', 'r', 'p', '[]',"
            " '2026-09-01T00:00:00+00:00', '2026-09-01T00:00:00+00:00')",
            (lab.id,),
        )

    await spaces.delete(lab.id)

    assert await spaces.get(lab.id) is None
    with db.read() as connection:
        left = connection.execute(
            "SELECT COUNT(*) FROM agent_defs WHERE space_id = ?", (lab.id,)
        )
        assert left.fetchone()[0] == 0
    with pytest.raises(SpaceNotFoundError):
        await spaces.require(lab.id)


@pytest.mark.anyio
async def test_the_folder_is_derived_from_the_id(
    spaces: SpaceStore, app_paths: AppPaths
) -> None:
    lab = await spaces.create({"name": "Lab"})
    assert spaces.folder_for(lab.id) == app_paths.spaces_dir / lab.id
    assert spaces.folder_for(lab.id) == app_paths.data_dir / "spaces" / lab.id
    # Not created on insert: listing spaces touches no disk.
    assert not spaces.folder_for(lab.id).exists()


# --- rules resolve in layers ------------------------------------------------


def _space(**overrides: object) -> Space:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return Space(id="s", name="S", created_at=now, updated_at=now, **overrides)  # type: ignore[arg-type]


def test_a_space_with_every_rule_null_leaves_the_workspace_settings_alone() -> None:
    workspace = WorkspaceSettings(auto_approve=[RiskLevel.LOW], max_run_seconds=300)
    assert _space().apply_to(workspace) is workspace


def test_model_and_limits_override() -> None:
    workspace = WorkspaceSettings(provider="ollama", model="qwen3:4b", max_run_seconds=300)
    effective = _space(provider="openai", model="gpt-5", max_run_seconds=1200).apply_to(
        workspace
    )
    assert (effective.provider, effective.model) == ("openai", "gpt-5")
    # Longer than the default is allowed: the wall clock is a cost control the
    # app-wide cap still bounds.
    assert effective.max_run_seconds == 1200
    assert effective.max_steps_per_agent == workspace.max_steps_per_agent


def test_the_approval_policy_only_narrows() -> None:
    """A space, like a definition, can never grant a level the app has not."""
    workspace = WorkspaceSettings(auto_approve=[RiskLevel.LOW, RiskLevel.MEDIUM])
    narrowed = _space(auto_approve=(RiskLevel.LOW,)).apply_to(workspace)
    assert narrowed.auto_approve == [RiskLevel.LOW]

    widened = _space(auto_approve=(RiskLevel.LOW, RiskLevel.HIGH)).apply_to(workspace)
    assert widened.auto_approve == [RiskLevel.LOW]

    # Empty narrows to nothing: the space *answered*, unlike NULL.
    nothing = _space(auto_approve=()).apply_to(workspace)
    assert nothing.auto_approve == []


def test_the_python_copy_of_the_built_in_roles_matches_what_the_migrations_seeded(
    db: Database,
) -> None:
    """Two copies of three roles (SQL for the first roster, Python for every
    later one) checked against each other rather than trusted."""
    from agentspace.store.builtins import BUILTIN_ROLES

    with db.read() as connection:
        rows = connection.execute(
            "SELECT name, role, system_prompt, allowed_tools FROM agent_defs"
            " WHERE is_builtin = 1 ORDER BY name"
        ).fetchall()
    seeded = {
        row["name"]: (
            row["role"],
            row["system_prompt"],
            tuple(json.loads(row["allowed_tools"])),
        )
        for row in rows
    }
    in_python = {
        role["name"]: (role["role"], role["system_prompt"], role["allowed_tools"])
        for role in BUILTIN_ROLES
    }
    assert in_python == seeded
