"""Migration 035: the risk manager reduces only for a risk an input names."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import Database

if TYPE_CHECKING:
    from pathlib import Path

_RISK = "714a2fec-4ddf-4583-922e-833b6abd4fd4"
_OLD_RULE = "- Under uncertainty, choose the more restrictive verdict."


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
    """The prompt with its line breaks flattened, so a phrase is found wherever it wraps."""
    with database.read() as connection:
        row = connection.execute(
            "SELECT system_prompt FROM agent_defs WHERE id = ?", (_RISK,)
        ).fetchone()
    return " ".join(str(row[0]).split())


def test_the_risk_manager_allows_an_ordinary_day(tmp_path: Path) -> None:
    """2026-10-14: every holding passed every rule, yet three were "reduce"
    for sharing a sector and for a routine 17-week bill auction."""
    database = Database(tmp_path / "fresh.sqlite3")
    database.connect()
    try:
        prompt = _prompt(database)
    finally:
        database.close()

    assert "Your job is to find reasons not" not in prompt
    assert _OLD_RULE not in prompt
    assert "- block: a hard rule FAILs. Nothing else blocks." in prompt
    assert "- allow: every rule passes and no input names such a risk." in prompt
    assert "a routine Treasury auction" in prompt
    assert "while max_sector_pct passes" in prompt
    assert "the newest raw/calendar-*.json" in prompt
    assert "for reduce, the ticker's current weight" in prompt
    # The hard rules and the copying rule are kept.
    assert "A hard-rule FAIL is always block. No exception is available." in prompt
    assert "Do no arithmetic and invent no replacement figure." in prompt


def test_an_edited_passage_keeps_its_edit(tmp_path: Path) -> None:
    path = tmp_path / "edited.sqlite3"
    before = _at_version(path, 34)
    with before.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET system_prompt = replace(system_prompt, ?, ?) WHERE id = ?",
            (_OLD_RULE, "- Be careful.", _RISK),
        )
    before.close()

    after = Database(path)
    after.connect()
    try:
        prompt = _prompt(after)
    finally:
        after.close()

    assert "- Be careful." in prompt
    assert "named risk's timing" not in prompt
    # The passages nobody edited still move.
    assert "- block: a hard rule FAILs. Nothing else blocks." in prompt
    assert "Your job is to find reasons not" not in prompt
