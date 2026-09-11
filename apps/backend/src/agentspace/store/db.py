"""SQLite connection management and the migration runner.

**Concurrency model.** One connection, guarded by a :class:`threading.Lock`.
The alternative — a connection per thread via ``threading.local`` — scales
better and is wrong for this application in two ways: connections owned by
pool threads are never deterministically closed, which on Windows keeps the
database file locked and makes both test teardown and app shutdown flaky; and
a single-user desktop app has no concurrency to scale to. Operations here are
sub-millisecond, and every async caller reaches them through
``asyncio.to_thread``, so the event loop is never blocked on the lock.

**Why the lock is not the correctness argument.** Sequence assignment in
:mod:`agentspace.events.store` is atomic because it runs as one statement
inside a ``BEGIN IMMEDIATE`` transaction with ``UNIQUE(run_id, seq)`` behind
it. That holds whether or not this lock exists. The lock is here to keep a
single ``sqlite3.Connection`` from being used by two threads at once, which is
a different problem; a later refactor that removes it must not silently remove
the atomicity guarantee with it.

**Migrations** step one version at a time via ``PRAGMA user_version``, each in
its own transaction. A migration that raises leaves the version untouched, so
the next launch retries it rather than skipping it forever.
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

logger = logging.getLogger("agentspace.store")


@dataclass(frozen=True, slots=True)
class Migration:
    """One forward schema step. There is no down-migration by design.

    Rolling a schema backwards on a user's machine loses their event log, and
    the event log is the product (§2). Recovery is a fresh database, not a
    reverse migration.
    """

    version: int
    sql: str

    #: Bundled filename this SQL came from, or ``None`` for a migration built
    #: in a test. Recorded so a test can assert the packaging glob in the
    #: justfile actually carries every file — a missing one is invisible until
    #: the frozen binary runs.
    source: str | None = None


def _load_sql(filename: str) -> str:
    """Read a bundled ``.sql`` file.

    ``importlib.resources`` rather than ``Path(__file__).parent`` because the
    shipped sidecar is a PyInstaller ``--onefile`` binary: at runtime the
    package lives inside an unpacked temp directory, and the justfile's
    ``--add-data`` places these files alongside the module there.
    """
    return (resources.files("agentspace.store") / filename).read_text(encoding="utf-8")


#: Version to bundled filename. Kept as data so the packaging test can walk it.
MIGRATION_FILES: tuple[tuple[int, str], ...] = (
    (1, "schema.sql"),
    (2, "002_spend_and_settings.sql"),
    (3, "003_agent_defs.sql"),
    (4, "004_approvals.sql"),
    (5, "005_drop_telegram.sql"),
)

#: Applied in order, each exactly once, lowest version first.
MIGRATIONS: tuple[Migration, ...] = tuple(
    Migration(version=version, sql=_load_sql(filename), source=filename)
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
            # The lock above provides the mutual exclusion sqlite3's own
            # same-thread check is a proxy for; `asyncio.to_thread` hands work
            # to arbitrary pool threads, so the check would fire spuriously.
            check_same_thread=False,
            # Transactions are opened explicitly in `write()`. Without this the
            # sqlite3 module inserts its own BEGIN at times of its choosing,
            # which defeats `BEGIN IMMEDIATE`.
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row

        # WAL: a reader (an SSE backlog fetch) does not block the writer (a run
        # appending events), which is the exact overlap this application has.
        connection.execute("PRAGMA journal_mode = WAL")
        # Off by default, and silently so — §4 declares a foreign key on
        # events.run_id and it is worthless unless this is on.
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA synchronous = NORMAL")
        # Wait rather than raising immediately if another connection (a second
        # app instance) holds the write lock.
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
        """Borrow the connection inside a write transaction.

        ``BEGIN IMMEDIATE`` takes the write lock up front rather than on first
        write, so a read-then-write sequence inside the block cannot interleave
        with another writer. Commits on clean exit, rolls back on any exception.
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

        The transaction control lives *inside* the script rather than around
        it. ``executescript`` issues an implicit COMMIT for any transaction
        already open before it runs, so a surrounding ``BEGIN IMMEDIATE``
        would be committed away and each statement of the migration would then
        autocommit individually — leaving a failed migration half applied with
        no way to roll it back.

        ``user_version`` is set in the same script, so the version advances if
        and only if every statement succeeded. A failure leaves it untouched
        and the next launch retries. It takes no parameter binding, hence the
        f-string; the value is an int from a module constant, never user input.
        """
        script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n"
            f"PRAGMA user_version = {int(migration.version)};\n"
            "COMMIT;"
        )

        with self._lock:
            connection = self._require_connection()
            try:
                connection.executescript(script)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
