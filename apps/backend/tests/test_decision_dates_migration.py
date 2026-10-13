"""Migration 033: the decision takes its date from the theses and finds its facts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import Database

if TYPE_CHECKING:
    from pathlib import Path

_DECISION = "3ea7f62a-6177-43c2-9367-3631dea22798"
_DAILY_DECISION = "c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33"
_OLD_DATE_RULE = "- Base the decision date on the newest theses filenames, not the local date."


def _at_version(path: Path, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def _texts(database: Database) -> tuple[str, str]:
    with database.read() as connection:
        prompt = connection.execute(
            "SELECT system_prompt FROM agent_defs WHERE id = ?", (_DECISION,)
        ).fetchone()[0]
        goal = connection.execute(
            "SELECT goal FROM schedules WHERE id = ?", (_DAILY_DECISION,)
        ).fetchone()[0]
    return str(prompt), str(goal)


def test_a_fresh_decision_is_told_its_date_and_where_the_facts_are(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    database.connect()
    try:
        prompt, goal = _texts(database)
    finally:
        database.close()

    assert "do not give decision a date or a file name yourself" in goal
    assert "the annual and quarterly facts in raw/filings/" in goal
    assert "no second pass is needed to read the workbook" in goal
    assert "raw/filings/{TICKER}.json for a company's" in prompt
    assert "predictions/*.xlsx is a binary workbook" in prompt
    assert "even when your task names another date or file" in prompt
    assert _OLD_DATE_RULE not in prompt
    # 031's forecast instructions are untouched.
    assert "Do not pass symbols, as_of or forecasts." in prompt


def test_an_edited_goal_and_an_edited_rule_keep_their_edits(tmp_path: Path) -> None:
    path = tmp_path / "edited.sqlite3"
    before = _at_version(path, 32)
    with before.write() as connection:
        connection.execute(
            "UPDATE schedules SET goal = 'My own decision goal.' WHERE id = ?",
            (_DAILY_DECISION,),
        )
        connection.execute(
            "UPDATE agent_defs SET system_prompt = replace(system_prompt, ?, ?) WHERE id = ?",
            (_OLD_DATE_RULE, "- Date the decision by the theses.", _DECISION),
        )
    before.close()

    after = Database(path)
    after.connect()
    try:
        prompt, goal = _texts(after)
    finally:
        after.close()

    assert goal == "My own decision goal."
    assert "- Date the decision by the theses." in prompt
    assert "even when your task names another date" not in prompt
    # The passage nobody edited still moves.
    assert "raw/filings/{TICKER}.json for a company's" in prompt
