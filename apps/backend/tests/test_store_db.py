"""Tests for the SQLite connection and the migration runner.

The migration runner is deliberately exercised as a *sequence*, not a one-shot
schema load. Phase 2 only needs `runs` and `events`; `spend`, `agent_defs` and
`approvals` arrive in the phases that use them (BUILD_SPEC §5 says do not build
ahead). A runner whose second migration has never executed is not a runner, so
the tests below apply a synthetic second migration to prove stepping works.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentspace.store import db as db_module
from agentspace.store.db import LATEST_SCHEMA_VERSION, Database, Migration

if TYPE_CHECKING:
    from pathlib import Path

    from agentspace.config import AppPaths


def _table_names(database: Database) -> set[str]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {row["name"] for row in rows}


# --- connection settings ----------------------------------------------------


def test_connect_creates_the_database_file(app_paths: AppPaths) -> None:
    assert not app_paths.db_path.exists()

    database = Database(app_paths.db_path)
    database.connect()
    try:
        assert app_paths.db_path.exists()
    finally:
        database.close()


def test_connect_creates_missing_parent_directories(tmp_path: Path) -> None:
    """The first launch on a fresh install has no app-data directory yet."""
    nested = tmp_path / "does" / "not" / "exist" / "agentspace.sqlite3"

    database = Database(nested)
    database.connect()
    try:
        assert nested.exists()
    finally:
        database.close()


def test_wal_mode_is_enabled(db: Database) -> None:
    """WAL lets the SSE backlog reads proceed while a run is still appending."""
    with db.read() as connection:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

    assert mode.lower() == "wal"


def test_foreign_keys_are_enforced(db: Database) -> None:
    """Off by default in SQLite, and silently so."""
    with db.read() as connection:
        enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1


def test_rows_are_accessible_by_column_name(db: Database) -> None:
    with db.read() as connection:
        row = connection.execute("SELECT 1 AS answer").fetchone()

    assert row["answer"] == 1


# --- migrations -------------------------------------------------------------


def test_migration_creates_phase_two_tables(db: Database) -> None:
    assert {"runs", "events"} <= _table_names(db)


def test_phase_two_does_not_create_later_phase_tables(db: Database) -> None:
    """BUILD_SPEC §5: do not build ahead.

    `spend`, `agent_defs` and `approvals` are specified in §4 but belong to
    Phases 3, 5 and 6. Creating them now would mean the migration runner never
    steps a second time before release.
    """
    assert _table_names(db).isdisjoint({"spend", "agent_defs", "approvals"})


def test_schema_version_is_recorded(db: Database) -> None:
    assert db.schema_version == LATEST_SCHEMA_VERSION


def test_migration_is_idempotent_across_reconnects(app_paths: AppPaths) -> None:
    """Every launch runs the migrator. Re-running must be a no-op, not an error."""
    for _ in range(3):
        database = Database(app_paths.db_path)
        database.connect()
        version = database.schema_version
        database.close()
        assert version == LATEST_SCHEMA_VERSION


def test_data_survives_a_reconnect(app_paths: AppPaths) -> None:
    first = Database(app_paths.db_path)
    first.connect()
    with first.write() as connection:
        connection.execute(
            "INSERT INTO runs (id, goal, status, origin, created_at) VALUES (?, ?, ?, ?, ?)",
            ("r1", "goal", "pending", "ui", "2026-09-09T00:00:00+00:00"),
        )
    first.close()

    second = Database(app_paths.db_path)
    second.connect()
    try:
        with second.read() as connection:
            row = connection.execute("SELECT goal FROM runs WHERE id = 'r1'").fetchone()
        assert row["goal"] == "goal"
    finally:
        second.close()


def test_runner_applies_only_migrations_above_the_current_version(
    app_paths: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second migration must apply to an already-migrated database.

    This is the case that a single bundled `schema.sql` never covers, and the
    one that breaks on a user's machine rather than on a fresh clone.
    """
    database = Database(app_paths.db_path)
    database.connect()
    database.close()

    extra = Migration(
        version=LATEST_SCHEMA_VERSION + 1, sql="CREATE TABLE later_phase (x INT);"
    )
    monkeypatch.setattr(db_module, "MIGRATIONS", (*db_module.MIGRATIONS, extra))

    upgraded = Database(app_paths.db_path)
    upgraded.connect()
    try:
        assert "later_phase" in _table_names(upgraded)
        assert upgraded.schema_version == LATEST_SCHEMA_VERSION + 1
    finally:
        upgraded.close()


def test_a_failing_migration_does_not_advance_the_version(
    app_paths: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-applied migration that reports success is unrecoverable in the
    field: the next launch skips it and the schema is wrong forever."""
    database = Database(app_paths.db_path)
    database.connect()
    database.close()

    broken = Migration(version=LATEST_SCHEMA_VERSION + 1, sql="THIS IS NOT SQL;")
    monkeypatch.setattr(db_module, "MIGRATIONS", (*db_module.MIGRATIONS, broken))

    failed = Database(app_paths.db_path)
    with pytest.raises(sqlite3.Error):
        failed.connect()
    failed.close()

    monkeypatch.undo()
    recovered = Database(app_paths.db_path)
    recovered.connect()
    try:
        assert recovered.schema_version == LATEST_SCHEMA_VERSION
    finally:
        recovered.close()


def test_migrations_are_ordered_and_unique() -> None:
    versions = [migration.version for migration in db_module.MIGRATIONS]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions[0] == 1


# --- schema shape -----------------------------------------------------------


def test_events_table_has_the_unique_run_seq_constraint(db: Database) -> None:
    """The backstop behind atomic seq assignment.

    Even if the INSERT logic is later refactored into a read-then-write race,
    this constraint turns a silently duplicated sequence number into an error.
    """
    with db.write() as connection:
        connection.execute(
            "INSERT INTO runs (id, goal, status, origin, created_at) VALUES (?, ?, ?, ?, ?)",
            ("r1", "g", "pending", "ui", "2026-09-09T00:00:00+00:00"),
        )
        connection.execute(
            "INSERT INTO events (run_id, seq, type, payload, ts) VALUES (?, ?, ?, ?, ?)",
            ("r1", 1, "run.started", "{}", "2026-09-09T00:00:00+00:00"),
        )

    with pytest.raises(sqlite3.IntegrityError), db.write() as connection:
        connection.execute(
            "INSERT INTO events (run_id, seq, type, payload, ts) VALUES (?, ?, ?, ?, ?)",
            ("r1", 1, "run.completed", "{}", "2026-09-09T00:00:01+00:00"),
        )


def test_write_rolls_back_on_error(db: Database) -> None:
    """`write()` is a transaction boundary, not just a cursor."""
    with pytest.raises(RuntimeError), db.write() as connection:
        connection.execute(
            "INSERT INTO runs (id, goal, status, origin, created_at) VALUES (?, ?, ?, ?, ?)",
            ("rollback-me", "g", "pending", "ui", "2026-09-09T00:00:00+00:00"),
        )
        raise RuntimeError("boom")

    with db.read() as connection:
        row = connection.execute("SELECT id FROM runs WHERE id = 'rollback-me'").fetchone()

    assert row is None
