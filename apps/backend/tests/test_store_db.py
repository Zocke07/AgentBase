"""Tests for the SQLite connection and the migration runner, exercised as a
sequence rather than a one-shot schema load. The synthetic-migration tests
prove stepping works past whatever the current head is;
`test_upgrade_preserves_an_existing_populated_database` runs the whole chain
over a database that already holds data.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from typing import TYPE_CHECKING

import pytest

from agentspace.store import db as db_module
from agentspace.store.db import LATEST_SCHEMA_VERSION, Database, Migration
from agentspace.store.settings import SettingsStore

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


def test_migration_creates_phase_three_tables(db: Database) -> None:
    """`spend` is §4 verbatim; `settings` backs the provider-switch criterion."""
    assert {"spend", "settings"} <= _table_names(db)


def test_migration_creates_the_agent_registry(db: Database) -> None:
    """`agent_defs` is §4 verbatim, and arrives with §5 Phase 5."""
    assert "agent_defs" in _table_names(db)


def test_every_table_the_data_model_specifies_now_exists(db: Database) -> None:
    """BUILD_SPEC §4's five tables, all present as of migration 004.

    This test previously asserted the opposite for `approvals`: that it did
    *not* exist, because §5 says not to build ahead and the table belonged to
    Phase 6's approval gate. Phase 6 is what changed it, and it is kept as a
    completeness check rather than deleted: §4 is a contract, and a migration
    that quietly dropped one of its tables should fail something.
    """
    tables = _table_names(db)

    assert {"runs", "events", "spend", "agent_defs", "approvals"} <= tables


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
            "INSERT INTO runs (id, space_id, goal, status, origin, created_at) VALUES (?, '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00', ?, ?, ?, ?)",
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
            "INSERT INTO runs (id, space_id, goal, status, origin, created_at) VALUES (?, '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00', ?, ?, ?, ?)",
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
            "INSERT INTO runs (id, space_id, goal, status, origin, created_at) VALUES (?, '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00', ?, ?, ?, ?)",
            ("rollback-me", "g", "pending", "ui", "2026-09-09T00:00:00+00:00"),
        )
        raise RuntimeError("boom")

    with db.read() as connection:
        row = connection.execute("SELECT id FROM runs WHERE id = 'rollback-me'").fetchone()

    assert row is None


# --- migration 005 -----------------------------------------------------------


def test_upgrade_drops_the_telegram_allowlist_entries_and_keeps_the_rest(
    app_paths: AppPaths,
) -> None:
    """A v4 database with a Telegram identity in its allowlist must still open.

    `channel_identities` is validated against the channels this build speaks,
    so an entry for the removed channel would fail on every read, taking
    `GET /settings`, and with it every run, down with it. The migration removes
    exactly those entries, keeps every other one, and drops the dead
    `telegram_enabled` row.
    """
    four = tuple(m for m in db_module.MIGRATIONS if m.version <= 4)
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = four
    first = Database(app_paths.db_path)
    try:
        first.connect()
        assert first.schema_version == 4
        with first.write() as connection:
            connection.executemany(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                [
                    (
                        "channel_identities",
                        json.dumps(
                            [
                                {
                                    "channel": "discord",
                                    "external_user_id": "1",
                                    "identity": "owner",
                                },
                                {
                                    "channel": "telegram",
                                    "external_user_id": "2",
                                    "identity": "owner",
                                },
                                {
                                    "channel": "discord",
                                    "external_user_id": "3",
                                    "identity": "friend",
                                },
                            ]
                        ),
                        "2026-09-01T00:00:00+00:00",
                    ),
                    ("telegram_enabled", "true", "2026-09-01T00:00:00+00:00"),
                    ("discord_enabled", "true", "2026-09-01T00:00:00+00:00"),
                ],
            )
    finally:
        first.close()
        db_module.MIGRATIONS = original

    upgraded = Database(app_paths.db_path)
    upgraded.connect()
    try:
        assert upgraded.schema_version == LATEST_SCHEMA_VERSION
        with upgraded.read() as connection:
            rows = {
                row["key"]: json.loads(row["value"])
                for row in connection.execute("SELECT key, value FROM settings")
            }
        assert rows["channel_identities"] == [
            {"channel": "discord", "external_user_id": "1", "identity": "owner"},
            {"channel": "discord", "external_user_id": "3", "identity": "friend"},
        ]
        assert "telegram_enabled" not in rows
        assert rows["discord_enabled"] is True

        # And the model reads it: this is the read that used to fail.
        settings = SettingsStore(upgraded)._get_sync()
        assert [entry.external_user_id for entry in settings.channel_identities] == ["1", "3"]
    finally:
        upgraded.close()


# --- migration 002 -----------------------------------------------------------


def test_upgrade_preserves_an_existing_populated_database(app_paths: AppPaths) -> None:
    """An upgrade must not disturb a v1 database that already has data.

    Every migration test before Phase 3 ran against a fresh file, and the
    shipped app upgrades over a user's existing event log. A migration that
    drops or rewrites data here is unrecoverable: there is no down-migration
    by design.

    The v1 schema is built explicitly rather than by monkeypatching MIGRATIONS
    down to one entry, so this walks the whole real chain (1 -> 2 -> 3) and
    keeps doing so as migrations are added.
    """
    first = Database(app_paths.db_path)
    monkeyed = (db_module.MIGRATIONS[0],)
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = monkeyed
    try:
        first.connect()
        assert first.schema_version == 1
        with first.write() as connection:
            connection.execute(
                "INSERT INTO runs (id, goal, status, origin, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("keepme", "pre-existing goal", "completed", "ui", "2026-09-01T00:00:00+00:00"),
            )
            connection.execute(
                "INSERT INTO events (run_id, seq, type, payload, ts) VALUES (?, ?, ?, ?, ?)",
                ("keepme", 1, "run.started", '{"goal":"x"}', "2026-09-01T00:00:00+00:00"),
            )
    finally:
        first.close()
        db_module.MIGRATIONS = original

    upgraded = Database(app_paths.db_path)
    upgraded.connect()
    try:
        assert upgraded.schema_version == LATEST_SCHEMA_VERSION
        assert {"spend", "settings", "agent_defs"} <= _table_names(upgraded)

        with upgraded.read() as connection:
            run = connection.execute("SELECT goal FROM runs WHERE id = 'keepme'").fetchone()
            events = connection.execute(
                "SELECT seq, type FROM events WHERE run_id = 'keepme'"
            ).fetchall()
            seeded = connection.execute(
                "SELECT name FROM agent_defs WHERE is_builtin = 1 ORDER BY name"
            ).fetchall()

        assert run["goal"] == "pre-existing goal"
        assert [(row["seq"], row["type"]) for row in events] == [(1, "run.started")]

        # Seeding happens on *upgrade*, not only on a fresh install. A user
        # who has been running since v1 must end up with a usable roster, or
        # migration 003 lands them an empty registry and no way to fill it
        # except the API they have not been told about. Since 010 that
        # roster is the investment pipeline.
        assert [row["name"] for row in seeded] == [
            "bear-architect",
            "bull-architect",
            "decision",
            "event-calendar",
            "market-movers",
            "news-scanner",
            "portfolio-review",
            "research-librarian",
            "review-analyst",
            "risk-manager",
        ]
    finally:
        upgraded.close()


def test_spend_table_matches_the_specified_columns(db: Database) -> None:
    """§4 specifies `spend` exactly; the ledger's integer-micros guarantee
    depends on `cost_micros` being an INTEGER column, not a REAL one."""
    with db.read() as connection:
        columns = {
            row["name"]: row["type"]
            for row in connection.execute("PRAGMA table_info(spend)").fetchall()
        }

    assert set(columns) == {
        "id",
        "run_id",
        "period",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_micros",
        "ts",
    }
    assert columns["cost_micros"] == "INTEGER"
    assert columns["input_tokens"] == "INTEGER"
    assert columns["output_tokens"] == "INTEGER"


def test_every_migration_file_is_bundled_by_the_packaging_glob() -> None:
    """The frozen sidecar reads migration SQL from a PyInstaller data bundle.

    `--add-data` in the justfile used to name `schema.sql` explicitly, so
    adding migration 002 would have produced a binary that starts and then dies
    on a missing resource: invisible to `just ci`, to every dev run, and to
    every test, because all of those read the file straight off the source
    tree. The glob fixes it; this asserts the glob stays.
    """
    justfile = pathlib.Path(__file__).resolve().parents[3] / "justfile"
    text = justfile.read_text(encoding="utf-8")

    assert 'migrations_sql := justfile_directory() / "apps" / "backend" / "src"' in text
    assert '"store" / "*.sql"' in text
    assert '--add-data "{{ migrations_sql }}{{ data_sep }}agentspace/store"' in text

    store_dir = pathlib.Path(db_module.__file__).resolve().parent
    on_disk = {path.name for path in store_dir.glob("*.sql")}
    registered = {filename for _, filename in db_module.MIGRATION_FILES}

    assert registered <= on_disk, (
        f"MIGRATION_FILES names files that do not exist: {registered - on_disk}"
    )
    assert on_disk == registered, (
        f"unregistered .sql files would still be bundled: {on_disk - registered}"
    )


def test_migration_files_and_migrations_agree() -> None:
    assert [version for version, _ in db_module.MIGRATION_FILES] == [
        migration.version for migration in db_module.MIGRATIONS
    ]
    assert all(migration.source is not None for migration in db_module.MIGRATIONS)


def test_agent_defs_table_matches_the_specified_columns(db: Database) -> None:
    """§4 specifies `agent_defs` exactly.

    Pinned the same way `spend` is, and for a related reason: `max_steps` being
    an INTEGER is what lets the registry clamp it against the workspace ceiling
    without a cast, and `name` being UNIQUE is what makes it safe to spawn by.
    """
    with db.read() as connection:
        columns = {
            row["name"]: row["type"]
            for row in connection.execute("PRAGMA table_info(agent_defs)").fetchall()
        }

    assert set(columns) == {
        "id",
        "space_id",
        "name",
        "role",
        "system_prompt",
        "provider",
        "model",
        "allowed_tools",
        "max_steps",
        "auto_approve",
        "is_builtin",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert columns["max_steps"] == "INTEGER"
    assert columns["is_builtin"] == "INTEGER"
    assert columns["enabled"] == "INTEGER"


def test_agent_name_is_unique_within_a_space(db: Database) -> None:
    """The constraint behind `DuplicateAgentNameError`.

    The store checks for a clash before inserting so the user gets a message
    naming the field; this is what holds if that check is ever refactored into
    a race.
    """
    with pytest.raises(sqlite3.IntegrityError), db.write() as connection:
        connection.execute(
            "INSERT INTO agent_defs (id, space_id, name, role, system_prompt, allowed_tools,"
            " max_steps, auto_approve, is_builtin, enabled, created_at, updated_at)"
            " VALUES ('x', '5c1e5a2e-0d4b-4c93-9a7f-3b2e8d1c6f00', 'decision', 'r', 'p',"
            " '[]', 5, '[]', 0, 1, 't', 't')"
        )
