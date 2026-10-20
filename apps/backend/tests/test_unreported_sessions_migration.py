"""Migration 036: a dated holdings file is noted, not a stop, and gaps are named."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import Database

if TYPE_CHECKING:
    from pathlib import Path

_REVIEW = "26846fbe-8a39-409a-9626-ccb84ab3e893"
_DECISION = "3ea7f62a-6177-43c2-9367-3631dea22798"
_OLD_STOP = "- If compute_portfolio reports a missing, stale or malformed required input,"


def _at_version(path: Path, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def _prompts(database: Database) -> tuple[str, str]:
    """Both prompts with line breaks flattened, so a phrase matches wherever it wraps."""
    with database.read() as connection:
        rows = {
            row[0]: " ".join(str(row[1]).split())
            for row in connection.execute(
                "SELECT id, system_prompt FROM agent_defs WHERE id IN (?, ?)",
                (_REVIEW, _DECISION),
            )
        }
    return rows[_REVIEW], rows[_DECISION]


def test_the_review_is_written_for_a_dated_holdings_file_and_gaps_are_named(
    tmp_path: Path,
) -> None:
    """2026-10-20: the holdings file had not been saved for a week, so its stale
    flag stopped the portfolio review; three unreported sessions went unsaid."""
    database = Database(tmp_path / "fresh.sqlite3")
    database.connect()
    try:
        review, decision = _prompts(database)
    finally:
        database.close()

    assert " ".join(_OLD_STOP.split()) not in review
    assert "reports a missing or malformed required input" in review
    assert "an unchanged holdings file is not an error" in review
    assert "every session in skipped_sessions as having no report" in review
    assert "portfolio/review-*.md, portfolio/computed.json, raw/calendar-*" in decision
    assert "say under the table that those sessions have no research or forecasts" in decision
    # The rest of each prompt is as shipped.
    assert "Preserve null realised and period P&L and their reasons" in review
    assert 'A risk verdict of "block" forces action "pass".' in decision


def test_an_edited_passage_keeps_its_edit(tmp_path: Path) -> None:
    path = tmp_path / "edited.sqlite3"
    before = _at_version(path, 35)
    with before.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET system_prompt = replace(system_prompt, ?, ?) WHERE id = ?",
            (_OLD_STOP, "- Stop when anything looks wrong,", _REVIEW),
        )
    before.close()

    after = Database(path)
    after.connect()
    try:
        review, decision = _prompts(after)
    finally:
        after.close()

    assert "- Stop when anything looks wrong," in review
    assert "reports a missing or malformed required input" not in review
    # The passages nobody edited still move.
    assert "an unchanged holdings file is not an error" in review
    assert "portfolio/computed.json, raw/calendar-*" in decision
