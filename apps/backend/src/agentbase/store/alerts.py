"""Market alerts the watcher recorded (BUILD_SPEC Phase 18).

One check's alerts share a batch, which one run explains. A batch's
explanation moves from ``queued`` (waiting for the space, or for the run to
be started) to ``running`` and then ``done`` or ``failed``; ``skipped`` means
the day's cap was reached and ``off`` that the space explains nothing.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    import sqlite3

    from agentbase.store.db import Database

__all__ = [
    "AlertStore",
    "ExplanationStatus",
    "MarketAlert",
    "NewAlert",
    "QueuedBatch",
]

ExplanationStatus = Literal["queued", "running", "done", "failed", "skipped", "off"]


class MarketAlert(BaseModel):
    id: str
    space_id: str
    batch_id: str
    symbol: str
    name: str | None
    instrument: Literal["stock", "index"]
    kind: Literal["move", "jump"]
    direction: Literal["up", "down"]
    change_pct: float
    level_pct: float
    price: float
    reference_price: float
    reference: Literal["previous_close", "regular_close", "window"]
    window_minutes: int | None
    session: Literal["pre", "regular", "post"]
    market_date: str
    quoted_at: str
    created_at: str
    explanation_status: ExplanationStatus
    explanation_run_id: str | None
    explanation_path: str | None
    explanation: str | None
    seen_at: str | None


@dataclass(frozen=True, slots=True)
class NewAlert:
    """What the watcher saw, before it is stored."""

    symbol: str
    name: str | None
    instrument: Literal["stock", "index"]
    kind: Literal["move", "jump"]
    direction: Literal["up", "down"]
    change_pct: float
    level_pct: float
    price: float
    reference_price: float
    reference: Literal["previous_close", "regular_close", "window"]
    window_minutes: int | None
    session: Literal["pre", "regular", "post"]
    market_date: str
    quoted_at: str


@dataclass(frozen=True, slots=True)
class QueuedBatch:
    batch_id: str
    space_id: str
    explanation_path: str
    alerts: tuple[MarketAlert, ...]


class AlertStore:
    """Reads and writes ``market_alerts``. Callers pass the time, so tests set it."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --- writes ------------------------------------------------------------

    async def record_batch(
        self,
        space_id: str,
        alerts: list[NewAlert],
        *,
        status: ExplanationStatus,
        explanation_path: str | None,
        now: datetime,
    ) -> list[MarketAlert]:
        return await asyncio.to_thread(
            self._record_sync, space_id, alerts, status, explanation_path, now
        )

    def _record_sync(
        self,
        space_id: str,
        alerts: list[NewAlert],
        status: ExplanationStatus,
        explanation_path: str | None,
        now: datetime,
    ) -> list[MarketAlert]:
        batch_id = str(uuid.uuid4())
        created_at = now.astimezone(UTC).isoformat()
        ids = [str(uuid.uuid4()) for _ in alerts]
        with self._db.write() as connection:
            for alert_id, alert in zip(ids, alerts, strict=True):
                connection.execute(
                    "INSERT INTO market_alerts (id, space_id, batch_id, symbol, name,"
                    " instrument, kind, direction, change_pct, level_pct, price,"
                    " reference_price, reference, window_minutes, session, market_date,"
                    " quoted_at, created_at, explanation_status, explanation_path)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        alert_id,
                        space_id,
                        batch_id,
                        alert.symbol,
                        alert.name,
                        alert.instrument,
                        alert.kind,
                        alert.direction,
                        alert.change_pct,
                        alert.level_pct,
                        alert.price,
                        alert.reference_price,
                        alert.reference,
                        alert.window_minutes,
                        alert.session,
                        alert.market_date,
                        alert.quoted_at,
                        created_at,
                        status,
                        explanation_path,
                    ),
                )
        return self._batch_sync(batch_id)

    async def set_batch(
        self,
        batch_id: str,
        status: ExplanationStatus,
        *,
        run_id: str | None = None,
        explanation: str | None = None,
    ) -> list[MarketAlert]:
        return await asyncio.to_thread(
            self._set_batch_sync, batch_id, status, run_id, explanation
        )

    def _set_batch_sync(
        self,
        batch_id: str,
        status: ExplanationStatus,
        run_id: str | None,
        explanation: str | None,
    ) -> list[MarketAlert]:
        with self._db.write() as connection:
            connection.execute(
                "UPDATE market_alerts SET explanation_status = ?,"
                " explanation_run_id = COALESCE(?, explanation_run_id),"
                " explanation = COALESCE(?, explanation)"
                " WHERE batch_id = ?",
                (status, run_id, explanation, batch_id),
            )
        return self._batch_sync(batch_id)

    async def mark_seen(self, space_id: str | None, now: datetime) -> int:
        """Mark every unseen alert in a space, or in all spaces, as seen."""
        return await asyncio.to_thread(self._mark_seen_sync, space_id, now)

    def _mark_seen_sync(self, space_id: str | None, now: datetime) -> int:
        stamp = now.astimezone(UTC).isoformat()
        with self._db.write() as connection:
            if space_id is None:
                cursor = connection.execute(
                    "UPDATE market_alerts SET seen_at = ? WHERE seen_at IS NULL", (stamp,)
                )
            else:
                cursor = connection.execute(
                    "UPDATE market_alerts SET seen_at = ? WHERE seen_at IS NULL AND space_id = ?",
                    (stamp, space_id),
                )
            return cursor.rowcount

    # --- reads -------------------------------------------------------------

    async def recent(self, space_id: str | None, limit: int) -> list[MarketAlert]:
        """Newest first, in a space or across them all."""
        return await asyncio.to_thread(self._recent_sync, space_id, limit)

    def _recent_sync(self, space_id: str | None, limit: int) -> list[MarketAlert]:
        with self._db.read() as connection:
            if space_id is None:
                rows = connection.execute(
                    "SELECT * FROM market_alerts ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM market_alerts WHERE space_id = ?"
                    " ORDER BY created_at DESC, rowid DESC LIMIT ?",
                    (space_id, limit),
                ).fetchall()
        return [_alert(row) for row in rows]

    async def unseen(self, space_id: str | None) -> int:
        return await asyncio.to_thread(self._unseen_sync, space_id)

    def _unseen_sync(self, space_id: str | None) -> int:
        with self._db.read() as connection:
            if space_id is None:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM market_alerts WHERE seen_at IS NULL"
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) AS n FROM market_alerts"
                    " WHERE seen_at IS NULL AND space_id = ?",
                    (space_id,),
                ).fetchone()
        return int(row["n"])

    async def day(self, space_id: str, market_date: str) -> list[MarketAlert]:
        """A space's alerts on one New York day, oldest first, for repeat checks."""
        return await asyncio.to_thread(self._day_sync, space_id, market_date)

    def _day_sync(self, space_id: str, market_date: str) -> list[MarketAlert]:
        with self._db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM market_alerts WHERE space_id = ? AND market_date = ?"
                " ORDER BY created_at, rowid",
                (space_id, market_date),
            ).fetchall()
        return [_alert(row) for row in rows]

    async def explanations_started(self, space_id: str, market_date: str) -> int:
        """Batches a run was started for that day: what the daily cap counts."""
        return await asyncio.to_thread(self._started_sync, space_id, market_date)

    def _started_sync(self, space_id: str, market_date: str) -> int:
        # A run was started for these, so they count against the day's cap.
        with self._db.read() as connection:
            row = connection.execute(
                "SELECT COUNT(DISTINCT batch_id) AS n FROM market_alerts"
                " WHERE space_id = ? AND market_date = ?"
                " AND explanation_status IN ('running', 'done', 'failed')",
                (space_id, market_date),
            ).fetchone()
        return int(row["n"])

    async def queued(self, space_id: str) -> list[QueuedBatch]:
        """Batches still waiting for their explanation run, oldest first."""
        return await asyncio.to_thread(self._queued_sync, space_id)

    def _queued_sync(self, space_id: str) -> list[QueuedBatch]:
        with self._db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM market_alerts WHERE space_id = ? AND explanation_status = 'queued'"
                " ORDER BY created_at, rowid",
                (space_id,),
            ).fetchall()
        batches: dict[str, list[MarketAlert]] = {}
        for row in rows:
            batches.setdefault(row["batch_id"], []).append(_alert(row))
        return [
            QueuedBatch(
                batch_id=batch_id,
                space_id=space_id,
                explanation_path=alerts[0].explanation_path or "",
                alerts=tuple(alerts),
            )
            for batch_id, alerts in batches.items()
        ]

    async def for_run(self, run_id: str) -> list[MarketAlert]:
        """The batch a run was started to explain; empty for any other run."""
        return await asyncio.to_thread(self._for_run_sync, run_id)

    def _for_run_sync(self, run_id: str) -> list[MarketAlert]:
        with self._db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM market_alerts WHERE explanation_run_id = ? ORDER BY created_at, rowid",
                (run_id,),
            ).fetchall()
        return [_alert(row) for row in rows]

    def _batch_sync(self, batch_id: str) -> list[MarketAlert]:
        with self._db.read() as connection:
            rows = connection.execute(
                "SELECT * FROM market_alerts WHERE batch_id = ? ORDER BY created_at, rowid",
                (batch_id,),
            ).fetchall()
        return [_alert(row) for row in rows]


def _alert(row: sqlite3.Row) -> MarketAlert:
    return MarketAlert.model_validate(dict(row))
