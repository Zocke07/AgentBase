"""Current models upgrade shipped defaults while preserving saved choices."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agentbase.store import db as db_module
from agentbase.store.db import Database
from agentbase.store.settings import DEFAULT_MODEL
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from pathlib import Path

_FAST = {"news-scanner", "market-movers", "event-calendar", "portfolio-review"}


def _at_version(path: Path, version: int) -> Database:
    """Migrate only so far: these tests are about 029, not what follows it."""
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def _version28(path: Path) -> Database:
    return _at_version(path, 28)


def _models(database: Database) -> dict[str, str]:
    with database.read() as connection:
        return {
            str(row["name"]): str(row["model"])
            for row in connection.execute("SELECT name,model FROM agent_defs")
        }


def test_untouched_fast_examples_upgrade_without_changing_other_fields(tmp_path: Path) -> None:
    path = tmp_path / "untouched.sqlite3"
    before = _version28(path)
    with before.read() as connection:
        original = {
            row["name"]: dict(row) for row in connection.execute("SELECT * FROM agent_defs")
        }
    before.close()

    after = _at_version(path, 29)
    try:
        with after.read() as connection:
            for row in connection.execute("SELECT * FROM agent_defs"):
                expected = original[row["name"]]
                if row["name"] in _FAST:
                    expected["model"] = "claude-haiku-5-5"
                assert dict(row) == expected
            assert (
                connection.execute("SELECT value FROM settings WHERE key='model'").fetchone()
                is None
            )
    finally:
        after.close()

    # Restart does not reapply or undo the migration.
    reopened = _at_version(path, 29)
    try:
        assert all(_models(reopened)[name] == "claude-haiku-5-5" for name in _FAST)
    finally:
        reopened.close()


@pytest.mark.parametrize(
    ("statement", "value"),
    [
        ("UPDATE agent_defs SET name=? WHERE name='news-scanner'", "my-scanner"),
        ("UPDATE agent_defs SET role=? WHERE name='news-scanner'", "My collector"),
        (
            "UPDATE agent_defs SET system_prompt=? WHERE name='news-scanner'",
            "Collect my own sources",
        ),
        ("UPDATE agent_defs SET allowed_tools=? WHERE name='news-scanner'", '["read_file"]'),
        ("UPDATE agent_defs SET max_steps=? WHERE name='news-scanner'", 7),
        ("UPDATE agent_defs SET auto_approve=? WHERE name='news-scanner'", '["low"]'),
        ("UPDATE agent_defs SET enabled=? WHERE name='news-scanner'", 0),
        ("UPDATE agent_defs SET is_builtin=? WHERE name='news-scanner'", 0),
        ("UPDATE agent_defs SET model=? WHERE name='news-scanner'", "claude-sonnet-5-5"),
    ],
)
def test_customized_example_rows_keep_their_model(
    tmp_path: Path, statement: str, value: str | int
) -> None:
    path = tmp_path / "edited.sqlite3"
    before = _version28(path)
    with before.write() as connection:
        # Preserve even direct edits that do not change the timestamp.
        connection.execute(statement, (value,))
        original = dict(
            connection.execute(
                "SELECT * FROM agent_defs WHERE id='c2a1ac57-ee48-4799-b94c-b01a051fdfe3'"
            ).fetchone()
        )
    before.close()

    after = _at_version(path, 29)
    try:
        with after.read() as connection:
            row = connection.execute(
                "SELECT * FROM agent_defs WHERE id='c2a1ac57-ee48-4799-b94c-b01a051fdfe3'"
            ).fetchone()
        assert dict(row) == original
        assert _models(after)["market-movers"] == "claude-haiku-5-5"
    finally:
        after.close()


def test_prior_prompt_migration_timestamps_do_not_skip_shipped_model_updates(
    tmp_path: Path,
) -> None:
    path = tmp_path / "older-install.sqlite3"
    before = _version28(path)
    with before.write() as connection:
        # This is the shape of a used installation after migration 028:
        # shipped prompt content is current but its timestamp was advanced.
        connection.execute(
            "UPDATE agent_defs SET created_at='2026-09-29T09:45:41+00:00', updated_at='2026-10-12T08:27:28+00:00'"
        )
        original = {
            row["name"]: dict(row) for row in connection.execute("SELECT * FROM agent_defs")
        }
    before.close()
    after = _at_version(path, 29)
    try:
        with after.read() as connection:
            for row in connection.execute("SELECT * FROM agent_defs"):
                expected = original[row["name"]]
                if row["name"] in _FAST:
                    expected["model"] = "claude-haiku-5-5"
                assert dict(row) == expected
    finally:
        after.close()


def test_custom_model_provider_and_global_choices_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "choices.sqlite3"
    before = _version28(path)
    with before.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET provider='openai',model='gpt-6-sol'"
            " WHERE name='market-movers'"
        )
        connection.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES ('model','\"gpt-6-sol\"','t')"
        )
        connection.execute(
            "UPDATE spaces SET provider='openai',model='gpt-6-sol',updated_at=created_at WHERE id=?",
            (DEFAULT_SPACE_ID,),
        )
    before.close()

    after = _at_version(path, 29)
    try:
        assert _models(after)["market-movers"] == "gpt-6-sol"
        with after.read() as connection:
            assert (
                json.loads(
                    connection.execute(
                        "SELECT value FROM settings WHERE key='model'"
                    ).fetchone()[0]
                )
                == "gpt-6-sol"
            )
            assert (
                connection.execute(
                    "SELECT model FROM spaces WHERE id=?", (DEFAULT_SPACE_ID,)
                ).fetchone()[0]
                == "gpt-6-sol"
            )
    finally:
        after.close()


@pytest.mark.parametrize("used", [False, True])
def test_only_an_unused_default_space_moves_to_the_new_openai_default(
    tmp_path: Path, used: bool
) -> None:
    path = tmp_path / "space.sqlite3"
    before = _version28(path)
    with before.write() as connection:
        connection.execute(
            "UPDATE spaces SET provider='openai',model='gpt-6-sol',updated_at=created_at WHERE id=?",
            (DEFAULT_SPACE_ID,),
        )
        if used:
            connection.execute(
                "INSERT INTO runs(id,space_id,goal,status,origin,created_at)"
                " VALUES('used',?,'prior run','completed','ui','2026-10-12')",
                (DEFAULT_SPACE_ID,),
            )
    before.close()

    after = _at_version(path, 29)
    try:
        with after.read() as connection:
            assert connection.execute(
                "SELECT model FROM spaces WHERE id=?", (DEFAULT_SPACE_ID,)
            ).fetchone()[0] == ("gpt-6-sol" if used else "gpt-6.1-sol")
            saved = connection.execute(
                "SELECT value FROM settings WHERE key='model'"
            ).fetchone()
        if used:
            assert saved is not None and json.loads(saved[0]) == DEFAULT_MODEL
        else:
            assert saved is None
    finally:
        after.close()


def test_an_edited_unused_default_space_keeps_its_selected_model(tmp_path: Path) -> None:
    path = tmp_path / "edited-space.sqlite3"
    before = _version28(path)
    with before.write() as connection:
        connection.execute(
            "UPDATE spaces SET provider='openai',model='gpt-6-sol',"
            "updated_at='2026-10-12T00:00:00+00:00' WHERE id=?",
            (DEFAULT_SPACE_ID,),
        )
    before.close()
    after = _at_version(path, 29)
    try:
        with after.read() as connection:
            assert (
                connection.execute(
                    "SELECT model FROM spaces WHERE id=?", (DEFAULT_SPACE_ID,)
                ).fetchone()[0]
                == "gpt-6-sol"
            )
    finally:
        after.close()
