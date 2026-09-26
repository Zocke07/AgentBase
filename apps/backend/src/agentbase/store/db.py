"""SQLite connection management and the migration runner.

One connection behind a :class:`threading.Lock`, not one per thread: pool
threads never deterministically close theirs, which on Windows keeps the file
locked through test teardown and app shutdown. The lock only keeps one
connection off two threads at once; `seq` atomicity comes from
``BEGIN IMMEDIATE`` and ``UNIQUE(run_id, seq)`` and holds without it.

Migrations step one version at a time via ``PRAGMA user_version``, each in
its own transaction, so a failed one is retried at the next launch.
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

    #: Bundled filename this SQL came from (``None`` in a test), so a test can
    #: check the packaging glob carries every file.
    source: str | None = None

    #: Run with ``PRAGMA foreign_keys`` off and verify with
    #: ``PRAGMA foreign_key_check`` before committing. A table rebuild is the
    #: only way SQLite adds a ``NOT NULL REFERENCES`` column, and the pragma
    #: cannot change inside a transaction, so the runner handles it.
    defer_foreign_keys: bool = False


def _load_sql(filename: str) -> str:
    """Read a bundled ``.sql`` file through ``importlib.resources``.

    ``Path(__file__)`` would not work inside the frozen binary.
    """
    return (resources.files("agentbase.store") / filename).read_text(encoding="utf-8")


#: Version to bundled filename. Kept as data so the packaging test can walk it.
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
)

#: The migrations that rebuild a table other tables reference. See
#: :attr:`Migration.defer_foreign_keys`.
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
            # The lock provides what the same-thread check is a proxy for.
            check_same_thread=False,
            # Transactions are opened explicitly in `write()`.
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row

        # WAL: an SSE backlog read does not block a run appending events.
        connection.execute("PRAGMA journal_mode = WAL")
        # Off by default; §4's foreign keys are worthless without it.
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
        """Borrow the connection inside a ``BEGIN IMMEDIATE`` transaction.

        The write lock is taken up front, so a read-then-write inside the
        block cannot interleave with another writer.
        """
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
        """Run one migration and bump ``user_version``, atomically.

        The BEGIN lives inside the script: ``executescript`` commits any open
        transaction before it runs, so a surrounding one would be committed
        away and a failed migration left half applied. ``user_version`` is set
        in the same script (an f-string, since a pragma takes no binding), so
        it advances only if every statement succeeded. A rebuild runs with
        the foreign-key check off and is checked by hand before the commit.
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
