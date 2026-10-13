"""Migration 034: the pipeline tools leave every space but the default."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from pathlib import Path

_NOW = "2026-10-01T00:00:00+00:00"


def _at_version(path: Path, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def _agent(
    connection: sqlite3.Connection,
    definition_id: str,
    space_id: str,
    name: str,
    tools: list[str],
) -> None:
    connection.execute(
        "INSERT INTO agent_defs (id, space_id, name, role, system_prompt, allowed_tools,"
        " max_steps, auto_approve, is_builtin, enabled, created_at, updated_at)"
        " VALUES (?, ?, ?, 'r', 'p', ?, 10, '[]', 0, 1, ?, ?)",
        (definition_id, space_id, name, json.dumps(tools), _NOW, _NOW),
    )


def test_another_spaces_agents_and_answers_keep_only_their_general_tools(
    tmp_path: Path,
) -> None:
    path = tmp_path / "upgrade.sqlite3"
    before = _at_version(path, 33)
    try:
        with before.write() as connection:
            connection.execute(
                "INSERT INTO spaces (id, name, tool_policies, created_at, updated_at)"
                " VALUES ('lab', 'Lab', ?, ?, ?)",
                (json.dumps({"read_prices": "deny", "write_file": "deny"}), _NOW, _NOW),
            )
            connection.execute(
                "INSERT INTO spaces (id, name, created_at, updated_at)"
                " VALUES ('quiet', 'Quiet', ?, ?)",
                (_NOW, _NOW),
            )
            _agent(
                connection, "a1", "lab", "prices", ["read_file", "read_prices", "write_file"]
            )
            _agent(connection, "a2", "lab", "plain", ["read_file", "http_get"])
            _agent(connection, "a3", DEFAULT_SPACE_ID, "mine", ["track_forecasts", "read_file"])
    finally:
        before.close()

    after = Database(path)
    after.connect()
    try:
        assert after.schema_version == LATEST_SCHEMA_VERSION
        with after.read() as connection:
            tools = {
                row["id"]: (json.loads(row["allowed_tools"]), row["updated_at"])
                for row in connection.execute(
                    "SELECT id, allowed_tools, updated_at FROM agent_defs"
                )
            }
            policies = {
                row["id"]: row["tool_policies"]
                for row in connection.execute("SELECT id, tool_policies FROM spaces")
            }
            shipped = connection.execute(
                "SELECT allowed_tools FROM agent_defs WHERE space_id = ? AND name = ?",
                (DEFAULT_SPACE_ID, "market-movers"),
            ).fetchone()
    finally:
        after.close()

    # In order, without the pipeline tool, and marked as changed.
    assert tools["a1"][0] == ["read_file", "write_file"]
    assert tools["a1"][1] != _NOW
    # Rows with nothing to remove are left exactly as they were.
    assert tools["a2"] == (["read_file", "http_get"], _NOW)
    assert tools["a3"] == (["track_forecasts", "read_file"], _NOW)
    # The default space's shipped pipeline keeps its tools.
    assert "read_prices" in json.loads(shipped["allowed_tools"])
    assert json.loads(policies["lab"]) == {"write_file": "deny"}
    assert policies["quiet"] is None
