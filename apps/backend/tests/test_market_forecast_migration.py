"""Upgrade preserves user choices while wiring the monthly forecast pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.settings import DEFAULT_AUTO_APPROVE_HOSTS, SettingsStore


def _version27(path: Path) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(item for item in original if item.version <= 27)
    database = Database(path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    return database


def test_fresh_pipeline_discovers_prices_then_records_all_five_horizons(tmp_path: Path) -> None:
    database = Database(tmp_path / "fresh.sqlite3")
    database.connect()
    try:
        with database.read() as connection:
            agents = {
                row["name"]: dict(row) for row in connection.execute("SELECT * FROM agent_defs")
            }
            goals = {
                row["name"]: row["goal"]
                for row in connection.execute("SELECT * FROM schedules")
            }
            morning = connection.execute(
                "SELECT cadence,enabled FROM schedules WHERE name='Morning collection'"
            ).fetchone()
        assert database.schema_version == LATEST_SCHEMA_VERSION
        assert json.loads(agents["news-scanner"]["allowed_tools"]) == [
            "read_market",
            "read_company_reports",
        ]
        assert "track_forecasts" in json.loads(agents["market-movers"]["allowed_tools"])
        assert "track_forecasts" in json.loads(agents["decision"]["allowed_tools"])
        assert "1|2|3|5|21" in agents["bull-architect"]["system_prompt"]
        assert "scenario_return_pct" in agents["decision"]["system_prompt"]
        assert "news-scanner first" in goals["Morning collection"]
        assert "Always call track_forecasts" in goals["Daily decision"]
        assert json.loads(morning["cadence"])["weekdays"] == [1, 2, 3, 4, 5]
        assert morning["enabled"] == 0
        assert SettingsStore(database)._get_sync().auto_approve_hosts == list(
            DEFAULT_AUTO_APPROVE_HOSTS
        )
    finally:
        database.close()


def test_used_upgrade_pins_hosts_preserves_models_and_updates_shipped_tools(
    tmp_path: Path,
) -> None:
    path = tmp_path / "used.sqlite3"
    before = _version27(path)
    with before.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET model='user-chosen',updated_at='2026-10-10' WHERE name='decision'"
        )
        connection.execute("UPDATE schedules SET enabled=1 WHERE name='Morning collection'")
    before.close()
    after = Database(path)
    after.connect()
    try:
        with after.read() as connection:
            decision = connection.execute(
                "SELECT model,allowed_tools FROM agent_defs WHERE name='decision'"
            ).fetchone()
            morning = connection.execute(
                "SELECT enabled,cadence FROM schedules WHERE name='Morning collection'"
            ).fetchone()
        assert decision["model"] == "user-chosen"
        assert "track_forecasts" in json.loads(decision["allowed_tools"])
        assert morning["enabled"] == 1
        assert json.loads(morning["cadence"])["weekdays"] == [0, 1, 2, 3, 4]
        assert SettingsStore(after)._get_sync().auto_approve_hosts == [
            "news.google.com",
            "query1.finance.yahoo.com",
            "api.fiscaldata.treasury.gov",
        ]
    finally:
        after.close()


def test_edited_agents_goals_and_network_policy_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "edited.sqlite3"
    before = _version27(path)
    with before.write() as connection:
        connection.execute(
            "UPDATE agent_defs SET system_prompt='My custom analysis' WHERE name='decision'"
        )
        connection.execute(
            "UPDATE agent_defs SET allowed_tools='[\"read_file\"]' WHERE name='news-scanner'"
        )
        connection.execute(
            'UPDATE schedules SET goal=\'My custom collection\',cadence=\'{"kind":"daily","at":"09:00"}\' WHERE name=\'Morning collection\''
        )
        connection.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES ('auto_approve_hosts','[\"feeds.example\"]','2026-10-10')"
        )
    before.close()
    after = Database(path)
    after.connect()
    try:
        with after.read() as connection:
            agents = {
                row["name"]: dict(row)
                for row in connection.execute(
                    "SELECT name,system_prompt,allowed_tools FROM agent_defs"
                )
            }
            morning = connection.execute(
                "SELECT goal,cadence FROM schedules WHERE name='Morning collection'"
            ).fetchone()
        assert agents["decision"]["system_prompt"] == "My custom analysis"
        assert agents["news-scanner"]["allowed_tools"] == '["read_file"]'
        assert morning["goal"] == "My custom collection"
        assert json.loads(morning["cadence"])["at"] == "09:00"
        assert SettingsStore(after)._get_sync().auto_approve_hosts == ["feeds.example"]
    finally:
        after.close()
