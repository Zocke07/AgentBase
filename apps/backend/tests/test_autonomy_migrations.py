"""Migrations that make autonomy the default without moving an upgraded install.

Each test builds a database at the version before the migration, fills it the
way a real install would be, and opens it with the full migration list.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.settings import SettingsStore

if TYPE_CHECKING:
    from agentbase.config import AppPaths

_NOW = "2026-09-28T00:00:00+00:00"


def _at_version(app_paths: AppPaths, version: int) -> Database:
    """A connected database migrated only as far as ``version``."""
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(m for m in original if m.version <= version)
    database = Database(app_paths.db_path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    assert database.schema_version == version
    return database


def _upgraded(app_paths: AppPaths) -> Database:
    database = Database(app_paths.db_path)
    database.connect()
    assert database.schema_version == LATEST_SCHEMA_VERSION
    return database


def _settings_rows(database: Database) -> dict[str, Any]:
    with database.read() as connection:
        return {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT key, value FROM settings")
        }


def _put_settings(database: Database, values: dict[str, Any]) -> None:
    with database.write() as connection:
        connection.executemany(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            [(key, json.dumps(value), _NOW) for key, value in values.items()],
        )


# --- migration 017: high risk is never answered by policy ---------------------


def test_017_strips_high_risk_answers_and_keeps_the_rest(app_paths: AppPaths) -> None:
    sixteen = _at_version(app_paths, 16)
    try:
        _put_settings(
            sixteen,
            {
                "auto_approve": ["low", "high"],
                "tool_policies": {"run_shell": "allow", "write_file": "allow"},
            },
        )
        with sixteen.write() as connection:
            connection.execute(
                "INSERT INTO spaces (id, name, auto_approve, tool_policies, created_at, updated_at)"
                " VALUES ('lab', 'Lab', ?, ?, ?, ?)",
                (
                    json.dumps(["high", "medium"]),
                    json.dumps({"run_shell": "allow", "read_file": "deny"}),
                    _NOW,
                    _NOW,
                ),
            )
            connection.execute(
                "INSERT INTO spaces (id, name, auto_approve, tool_policies, created_at, updated_at)"
                " VALUES ('quiet', 'Quiet', NULL, ?, ?, ?)",
                (json.dumps({"run_shell": "deny"}), _NOW, _NOW),
            )
    finally:
        sixteen.close()

    upgraded = _upgraded(app_paths)
    try:
        rows = _settings_rows(upgraded)
        assert rows["auto_approve"] == ["low"]
        assert rows["tool_policies"] == {"write_file": "allow"}
        with upgraded.read() as connection:
            spaces = {
                row["id"]: row
                for row in connection.execute(
                    "SELECT id, auto_approve, tool_policies FROM spaces"
                )
            }
        assert json.loads(spaces["lab"]["auto_approve"]) == ["medium"]
        assert json.loads(spaces["lab"]["tool_policies"]) == {"read_file": "deny"}
        # Inheriting stays inheriting, and a refusal of the shell stays.
        assert spaces["quiet"]["auto_approve"] is None
        assert json.loads(spaces["quiet"]["tool_policies"]) == {"run_shell": "deny"}
        # The stricter model reads what the migration left.
        settings = SettingsStore(upgraded)._get_sync()
        assert [str(level) for level in settings.auto_approve] == ["low"]
    finally:
        upgraded.close()
