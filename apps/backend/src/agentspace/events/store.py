"""Append-only event storage and run bookkeeping.

Everything here is `async def` over a blocking SQLite driver, with the actual
work handed to `asyncio.to_thread`. That is deliberate rather than incidental:
it keeps the event loop free, and it means the concurrency test in
`test_event_store.py` produces real thread contention on the write lock instead
of a cooperative interleaving that would never expose a race.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

from agentspace.events.types import Event, EventType, Run, RunOrigin, RunStatus
from agentspace.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    import sqlite3

    from agentspace.events.bus import EventBus
    from agentspace.store.db import Database

__all__ = ["DEFAULT_RUN_LIST_LIMIT", "MAX_RUN_LIST_LIMIT", "EventStore"]

#: How many runs :meth:`EventStore.list_runs` returns when nobody says.
DEFAULT_RUN_LIST_LIMIT: Final[int] = 50

#: The ceiling `GET /runs` accepts. A workspace accumulates runs forever and
#: the picker renders them all at once, so the bound is the UI's protection
#: rather than the database's.
MAX_RUN_LIST_LIMIT: Final[int] = 500

#: Statuses after which a run is over and `finished_at` is stamped.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

#: One statement, so that reading the current maximum and writing the next
#: value cannot be separated by another writer. Combined with the
#: `BEGIN IMMEDIATE` in `Database.write()` and the `UNIQUE(run_id, seq)`
#: constraint, a duplicate sequence number is impossible rather than unlikely.
_APPEND_SQL = """
INSERT INTO events (run_id, seq, agent_id, type, payload, ts)
VALUES (
    :run_id,
    (SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE run_id = :run_id),
    :agent_id,
    :type,
    :payload,
    :ts
)
RETURNING id, seq
"""


def _now() -> datetime:
    """Timezone-aware UTC. ruff's DTZ rules ban the naive alternative."""
    return datetime.now(UTC)


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        run_id=row["run_id"],
        seq=row["seq"],
        agent_id=row["agent_id"],
        type=EventType(row["type"]),
        payload=json.loads(row["payload"]),
        ts=datetime.fromisoformat(row["ts"]),
    )


def _row_to_run(row: sqlite3.Row) -> Run:
    finished = row["finished_at"]
    return Run(
        id=row["id"],
        space_id=row["space_id"],
        goal=row["goal"],
        status=row["status"],
        origin=row["origin"],
        origin_ref=row["origin_ref"],
        created_at=datetime.fromisoformat(row["created_at"]),
        finished_at=datetime.fromisoformat(finished) if finished else None,
    )


class EventStore:
    """Reads and writes the event log, and publishes what it wrote.

    The bus is optional so the store can be used — and tested — without one.
    Publication happens only after the transaction commits, so a subscriber can
    never observe an event that a rollback later erased.
    """

    def __init__(self, db: Database, bus: EventBus | None = None) -> None:
        self._db = db
        self._bus = bus

    # --- events ------------------------------------------------------------

    async def append(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
        agent_id: str | None = None,
    ) -> Event:
        """Append one event and return it with its assigned sequence number."""
        event = await asyncio.to_thread(
            self._append_sync, run_id, event_type, payload or {}, agent_id
        )

        if self._bus is not None:
            # Synchronous, and deliberately so — see EventBus.publish.
            self._bus.publish(event)

        return event

    def _append_sync(
        self,
        run_id: str,
        event_type: EventType,
        payload: dict[str, Any],
        agent_id: str | None,
    ) -> Event:
        ts = _now()
        parameters = {
            "run_id": run_id,
            "agent_id": agent_id,
            "type": str(event_type),
            "payload": json.dumps(payload, separators=(",", ":")),
            "ts": ts.isoformat(),
        }

        with self._db.write() as connection:
            row = connection.execute(_APPEND_SQL, parameters).fetchone()

        return Event(
            id=row["id"],
            run_id=run_id,
            seq=row["seq"],
            agent_id=agent_id,
            type=event_type,
            payload=payload,
            ts=ts,
        )

    async def read(
        self,
        run_id: str,
        after_seq: int = 0,
        until_seq: int | None = None,
    ) -> list[Event]:
        """Return events for ``run_id`` ordered by ``seq``.

        ``after_seq`` is exclusive: it names the last event the caller already
        holds, which is exactly what ``Last-Event-ID`` means.
        """
        return await asyncio.to_thread(self._read_sync, run_id, after_seq, until_seq)

    def _read_sync(self, run_id: str, after_seq: int, until_seq: int | None) -> list[Event]:
        sql = "SELECT * FROM events WHERE run_id = ? AND seq > ?"
        parameters: list[Any] = [run_id, after_seq]

        if until_seq is not None:
            sql += " AND seq <= ?"
            parameters.append(until_seq)

        sql += " ORDER BY seq"

        with self._db.read() as connection:
            rows = connection.execute(sql, parameters).fetchall()

        return [_row_to_event(row) for row in rows]

    async def max_seq(self, run_id: str) -> int:
        """The highest sequence number stored for ``run_id``, or 0 if none."""
        return await asyncio.to_thread(self._max_seq_sync, run_id)

    def _max_seq_sync(self, run_id: str) -> int:
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(seq), 0) AS head FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return int(row["head"])

    # --- runs --------------------------------------------------------------

    async def create_run(
        self,
        goal: str,
        origin: RunOrigin = "ui",
        origin_ref: str | None = None,
        space_id: str = DEFAULT_SPACE_ID,
    ) -> Run:
        """Insert a run row.

        This creates the row only. Attaching an orchestrator to it is Phase 4;
        until then a run's status moves because something explicitly moves it.
        The space defaults so that every caller that predates spaces — the
        debug script, a chat command with no space configured — lands in the
        default one, which migration 006 guarantees exists.
        """
        return await asyncio.to_thread(
            self._create_run_sync, goal, origin, origin_ref, space_id
        )

    def _create_run_sync(
        self, goal: str, origin: RunOrigin, origin_ref: str | None, space_id: str
    ) -> Run:
        run = Run(
            id=str(uuid.uuid4()),
            space_id=space_id,
            goal=goal,
            status="pending",
            origin=origin,
            origin_ref=origin_ref,
            created_at=_now(),
        )

        with self._db.write() as connection:
            connection.execute(
                "INSERT INTO runs (id, space_id, goal, status, origin, origin_ref, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    run.space_id,
                    run.goal,
                    run.status,
                    run.origin,
                    run.origin_ref,
                    run.created_at.isoformat(),
                ),
            )

        return run

    async def list_runs(
        self, limit: int = DEFAULT_RUN_LIST_LIMIT, space_id: str | None = None
    ) -> list[Run]:
        """Recent runs, newest first — what the Phase 7 replay picker reads.

        Reads the `runs` table rather than deriving the list from events. The
        event log is the authority on what *happened* in a run (§2); it is not
        the authority on which runs exist, and a run created but never started
        has no events at all. That run is precisely the one a user goes looking
        for an explanation of, so a listing that omitted it would be worse than
        useless. ``space_id`` narrows the list to one space's runs.
        """
        return await asyncio.to_thread(self._list_runs_sync, limit, space_id)

    def _list_runs_sync(self, limit: int, space_id: str | None) -> list[Run]:
        where = "" if space_id is None else " WHERE space_id = ?"
        params: tuple[Any, ...] = (limit,) if space_id is None else (space_id, limit)
        with self._db.read() as connection:
            rows = connection.execute(
                # `rowid` breaks the tie. `created_at` is an ISO timestamp and
                # two runs started in the same microsecond would otherwise come
                # back in whatever order SQLite chose, which makes the ordering
                # test flaky rather than the ordering wrong.
                f"SELECT * FROM runs{where} ORDER BY created_at DESC, rowid DESC LIMIT ?",  # noqa: S608
                params,
            ).fetchall()

        return [_row_to_run(row) for row in rows]

    async def get_run(self, run_id: str) -> Run | None:
        return await asyncio.to_thread(self._get_run_sync, run_id)

    def _get_run_sync(self, run_id: str) -> Run | None:
        with self._db.read() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

        return _row_to_run(row) if row is not None else None

    async def set_run_status(self, run_id: str, status: RunStatus) -> None:
        """Move a run's status, stamping ``finished_at`` on terminal states."""
        await asyncio.to_thread(self._set_run_status_sync, run_id, status)

    def _set_run_status_sync(self, run_id: str, status: RunStatus) -> None:
        finished_at = _now().isoformat() if status in _TERMINAL_STATUSES else None

        with self._db.write() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, finished_at = ? WHERE id = ?",
                (status, finished_at, run_id),
            )

    async def fail_orphaned_runs(self, reason: str) -> list[str]:
        """Fail every run a previous process left unfinished. Called at startup.

        A run's orchestrator is an ``asyncio`` task in the process that started
        it; a crash or a closed window ends the task and nothing else. The row
        stayed ``running`` forever — at the top of the picker — and opening it
        held a stream that never ended, because nothing would ever append its
        terminal event. The dashboard said "live" about a run that had been
        dead since the app last closed.

        The terminal event is appended first, so the log stays the authority
        on what happened (§2) and a replay shows the run ending with a reason;
        the row is moved to match. Runs already at a terminal status are not
        touched: the sweep must not rewrite history it did not create.
        """
        orphaned = await asyncio.to_thread(self._unfinished_run_ids_sync)
        for run_id in orphaned:
            await self.append(run_id, EventType.RUN_FAILED, {"reason": reason})
            await self.set_run_status(run_id, "failed")
        return orphaned

    def _unfinished_run_ids_sync(self) -> list[str]:
        placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)
        with self._db.read() as connection:
            rows = connection.execute(
                f"SELECT id FROM runs WHERE status NOT IN ({placeholders}) "  # noqa: S608
                "ORDER BY created_at, rowid",
                tuple(sorted(_TERMINAL_STATUSES)),
            ).fetchall()
        return [str(row["id"]) for row in rows]
