"""SQLite connection and migration management.

One lock-protected connection avoids leaked thread-local files. Migrations
advance ``PRAGMA user_version`` one transaction at a time, retrying failures
at the next launch.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

__all__ = [
    "LATEST_SCHEMA_VERSION",
    "MIGRATIONS",
    "MIGRATION_FILES",
    "Database",
    "Migration",
]

logger = logging.getLogger("agentbase.store")


@dataclass(frozen=True, slots=True)
class Migration:
    """One forward schema step. No down-migrations: rolling back loses the event log."""

    version: int
    sql: str

    #: Bundled SQL filename; ``None`` for inline test migrations.
    source: str | None = None

    #: Disable foreign-key checks for a table rebuild, then verify before commit.
    defer_foreign_keys: bool = False


def _load_sql(filename: str) -> str:
    """Read bundled SQL through ``importlib.resources`` for frozen builds."""
    return (resources.files("agentbase.store") / filename).read_text(encoding="utf-8")


#: Migration version-to-filename map, also used by packaging tests.
MIGRATION_FILES: tuple[tuple[int, str], ...] = (
    (1, "schema.sql"),
    (2, "002_spend_and_settings.sql"),
    (3, "003_agent_defs.sql"),
    (4, "004_approvals.sql"),
    (5, "005_drop_telegram.sql"),
    (6, "006_spaces.sql"),
    (7, "007_knowledge.sql"),
    (8, "008_memory_inbox.sql"),
    (9, "009_schedules.sql"),
    (10, "010_investment_roster.sql"),
    (11, "011_tool_policies.sql"),
    (12, "012_space_models_and_schedule_limits.sql"),
    (13, "013_news_scanner_reads.sql"),
    (14, "014_run_cost_limit.sql"),
    (15, "015_news_feed_reader.sql"),
    (16, "016_space_providers_and_opus_5_5.sql"),
    (17, "017_high_risk_never_automatic.sql"),
    (18, "018_autonomous_defaults.sql"),
    (19, "019_autonomous_examples.sql"),
    (20, "020_sonnet_5_5_and_space_defaults.sql"),
    (21, "021_investment_pipeline.sql"),
    (22, "022_repair_investment_roster.sql"),
    (23, "023_theses_stage.sql"),
    (24, "024_pipeline_prompts.sql"),
    (25, "025_portfolio_session_date.sql"),
    (26, "026_decision_date_and_calendar_fields.sql"),
    (27, "027_decision_sources.sql"),
)

#: Migrations requiring deferred foreign-key checks.
_REBUILDS: frozenset[int] = frozenset({6})

#: Applied in order, each exactly once, lowest version first.
MIGRATIONS: tuple[Migration, ...] = tuple(
    Migration(
        version=version,
        sql=_load_sql(filename),
        source=filename,
        defer_foreign_keys=version in _REBUILDS,
    )
    for version, filename in MIGRATION_FILES
)

LATEST_SCHEMA_VERSION: Final[int] = max(migration.version for migration in MIGRATIONS)


class Database:
    """A single SQLite connection plus its migration state."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._connection: sqlite3.Connection | None = None

    # --- lifecycle ---------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> None:
        """Open the database, apply pragmas, and migrate to the latest version."""
        self._path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(
            self._path,
            # The lock guarantees single-threaded connection access.
            check_same_thread=False,
            # ``write()`` opens transactions explicitly.
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row

        # WAL keeps event appends available during SSE backlog reads.
        connection.execute("PRAGMA journal_mode = WAL")
        # SQLite disables foreign-key enforcement by default.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")

        self._connection = connection
        self._migrate()

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    # --- access ------------------------------------------------------------

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            msg = "database is not connected; call connect() first"
            raise RuntimeError(msg)
        return self._connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        """Borrow the connection for a read. No transaction is opened."""
        with self._lock:
            yield self._require_connection()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Borrow the connection inside a ``BEGIN IMMEDIATE`` transaction."""
        with self._lock:
            connection = self._require_connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")

    # --- migrations --------------------------------------------------------

    @property
    def schema_version(self) -> int:
        with self.read() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        return int(version)

    def _migrate(self) -> None:
        current = self.schema_version

        for migration in MIGRATIONS:
            if migration.version <= current:
                continue

            logger.info("applying migration %d", migration.version)
            self._apply(migration)
            current = migration.version

    def _apply(self, migration: Migration) -> None:
        """Apply one migration and advance ``user_version`` atomically.

        Keep ``BEGIN`` in the script because ``executescript`` commits an open
        transaction. Rebuild migrations verify foreign keys before commit.
        """
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n"
            f"PRAGMA user_version = {int(migration.version)};\n"
        )

        with self._lock:
            connection = self._require_connection()
            if migration.defer_foreign_keys:
                connection.execute("PRAGMA foreign_keys = OFF")
            try:
                connection.executescript(script)
                if migration.defer_foreign_keys:
                    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                    if violations:
                        tables = sorted({str(row[0]) for row in violations})
                        msg = (
                            f"migration {migration.version} left foreign key violations in "
                            f"{', '.join(tables)}; rolled back"
                        )
                        raise sqlite3.IntegrityError(msg)
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                if migration.defer_foreign_keys:
                    connection.execute("PRAGMA foreign_keys = ON")
