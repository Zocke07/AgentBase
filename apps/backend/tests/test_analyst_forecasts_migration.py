"""Migration 031: the decision lets track_forecasts read the session's theses."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import Database

if TYPE_CHECKING:
    from pathlib import Path

_DECISION = "3ea7f62a-6177-43c2-9367-3631dea22798"
_DAILY_DECISION = "c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33"
_WEEKLY_REVIEW = "ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55"
_OLD_INSTRUCTION = "copy expected_return_pct to"


def _at_version(path: Path, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def _prompt(database: Database) -> str:
    with database.read() as connection:
        row = connection.execute(
            "SELECT system_prompt FROM agent_defs WHERE id = ?", (_DECISION,)
        ).fetchone()
    return str(row[0])


def _goal(database: Database, schedule_id: str) -> str:
    with database.read() as connection:
        row = connection.execute(
            "SELECT goal FROM schedules WHERE id = ?", (schedule_id,)
        ).fetchone()
    return str(row[0])


def test_a_fresh_decision_calls_the_tracker_with_no_arguments(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    database.connect()
    try:
        prompt = _prompt(database)
        assert _OLD_INSTRUCTION not in prompt
        assert "4. FORECAST TRACKING: call track_forecasts once, with no arguments" in prompt
        assert "Do not pass symbols, as_of or forecasts." in prompt
        assert "When not_issued says the market is\n  trading" in prompt
        # The rest of the shipped prompt is untouched.
        assert "3. SOURCES:" in prompt and "5. WATCH:" in prompt
        assert "- Forecasts are immutable once saved." in prompt
        assert "track_forecasts once with no arguments" in _goal(database, _DAILY_DECISION)
        assert "analyst thesis and agent scenario forecast coverage" in _goal(
            database, _WEEKLY_REVIEW
        )
    finally:
        database.close()


def test_an_edited_forecast_passage_keeps_its_edit(tmp_path: Path) -> None:
    path = tmp_path / "edited.sqlite3"
    before = _at_version(path, 30)
    with before.write() as connection:
        # A person rewrote the forecast instructions and changed the model;
        # the other passage is still the shipped text.
        connection.execute(
            "UPDATE agent_defs SET model = 'claude-sonnet-5-5', updated_at = '2026-10-12T00:00:00Z',"
            " system_prompt = replace(system_prompt, ?, ?) WHERE id = ?",
            (_OLD_INSTRUCTION, "copy my own scenario to", _DECISION),
        )
        connection.execute(
            "UPDATE schedules SET goal = 'My own decision goal.' WHERE id = ?",
            (_DAILY_DECISION,),
        )
    before.close()

    after = Database(path)
    after.connect()
    try:
        prompt = _prompt(after)
        assert "copy my own scenario to" in prompt
        assert "Do not pass symbols" not in prompt
        assert "4. FORECAST TRACKING: call track_forecasts once, with no arguments" in prompt
        assert _goal(after, _DAILY_DECISION) == "My own decision goal."
        with after.read() as connection:
            model, updated_at = connection.execute(
                "SELECT model, updated_at FROM agent_defs WHERE id = ?", (_DECISION,)
            ).fetchone()
        assert (model, updated_at) == ("claude-sonnet-5-5", "2026-10-12T00:00:00Z")
    finally:
        after.close()
