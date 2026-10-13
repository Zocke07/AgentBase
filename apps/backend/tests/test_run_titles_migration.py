"""Migration 032: earlier automation runs take their schedule's name."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import Database
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from pathlib import Path

_MORNING = "a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11"


def _at_version(path: Path, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def test_earlier_runs_are_named_after_their_schedule_or_alert(tmp_path: Path) -> None:
    path = tmp_path / "titles.sqlite3"
    before = _at_version(path, 31)
    rows = [
        ("timed", "schedule", _MORNING),
        ("by-hand", "automation", _MORNING),
        ("gone", "schedule", "a-deleted-schedule"),
        ("alert", "monitor", "batch-1"),
        ("mine", "ui", None),
    ]
    with before.write() as connection:
        for run_id, origin, ref in rows:
            connection.execute(
                "INSERT INTO runs (id, space_id, goal, status, origin, origin_ref, created_at)"
                " VALUES (?, ?, 'a long goal', 'completed', ?, ?, '2026-10-13T00:00:00+00:00')",
                (run_id, DEFAULT_SPACE_ID, origin, ref),
            )
        for number, symbol in enumerate(("MU", "^IXIC", "MU")):
            connection.execute(
                "INSERT INTO market_alerts (id, space_id, batch_id, symbol, instrument, kind,"
                " direction, change_pct, level_pct, price, reference_price, reference,"
                " session, market_date, quoted_at, created_at, explanation_status,"
                " explanation_run_id)"
                " VALUES (?, ?, 'batch-1', ?, 'stock', 'move', 'down', -5, -5, 95, 100,"
                " 'previous_close', 'regular', '2026-10-12', '2026-10-12T15:00:00Z',"
                " '2026-10-12T15:00:00Z', 'done', 'alert')",
                (f"alert-{number}", DEFAULT_SPACE_ID, symbol),
            )
    before.close()

    after = Database(path)
    after.connect()
    try:
        with after.read() as connection:
            titles = dict(connection.execute("SELECT id, title FROM runs").fetchall())
    finally:
        after.close()

    assert titles == {
        "timed": "Morning collection",
        "by-hand": "Morning collection",
        "gone": None,
        "alert": "Market alert: MU, ^IXIC",
        "mine": None,
    }
