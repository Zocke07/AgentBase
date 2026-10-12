"""Migration 030: the market-alert table and the shipped explainer (Phase 18)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from pathlib import Path

_NEWS_SCANNER = "c2a1ac57-ee48-4799-b94c-b01a051fdfe3"


def _at_version(path: Path, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= version)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def _explainers(database: Database) -> list[dict[str, object]]:
    with database.read() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT name, provider, model, allowed_tools, is_builtin, enabled, system_prompt"
                " FROM agent_defs WHERE space_id = ? AND name = 'market-explainer'",
                (DEFAULT_SPACE_ID,),
            )
        ]


def test_a_fresh_install_gets_the_alert_table_and_a_fast_explainer(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    database.connect()
    try:
        assert database.schema_version == LATEST_SCHEMA_VERSION
        with database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM market_alerts").fetchone()[0] == 0
        [explainer] = _explainers(database)
        assert (explainer["provider"], explainer["model"]) == ("anthropic", "claude-haiku-5-5")
        assert json.loads(str(explainer["allowed_tools"])) == [
            "read_feed",
            "read_file",
            "list_dir",
            "search_knowledge",
            "write_file",
        ]
        assert explainer["is_builtin"] == 1 and explainer["enabled"] == 1
        prompt = str(explainer["system_prompt"])
        assert "never predict" in prompt and "No clear reason found" in prompt
    finally:
        database.close()


def test_the_explainer_takes_the_model_a_plan_switch_gave_the_news_scanner(
    tmp_path: Path,
) -> None:
    # A ChatGPT plan without GPT-6 Luna: the space's fast agents moved to GPT-5.6 Luna.
    path = tmp_path / "chatgpt.sqlite3"
    before = _at_version(path, 29)
    with before.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET provider = 'openai', model = 'gpt-5.6-luna' WHERE id = ?",
            (_NEWS_SCANNER,),
        )
    before.close()

    after = Database(path)
    after.connect()
    try:
        [explainer] = _explainers(after)
        assert (explainer["provider"], explainer["model"]) == ("openai", "gpt-5.6-luna")
    finally:
        after.close()


def test_an_agent_already_called_market_explainer_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "mine.sqlite3"
    before = _at_version(path, 29)
    with before.write() as connection:
        connection.execute(
            "INSERT INTO agent_defs (id, space_id, name, role, system_prompt, allowed_tools,"
            " max_steps, auto_approve, is_builtin, enabled, created_at, updated_at)"
            " VALUES ('mine', ?, 'market-explainer', 'Mine', 'My way.', '[]', 5, '[]', 0, 1,"
            " '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')",
            (DEFAULT_SPACE_ID,),
        )
    before.close()

    after = Database(path)
    after.connect()
    try:
        [explainer] = _explainers(after)
        assert explainer["system_prompt"] == "My way." and explainer["is_builtin"] == 0
    finally:
        after.close()
