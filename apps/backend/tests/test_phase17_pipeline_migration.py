"""Migration 021 wires the deterministic tools without overwriting edits."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.settings import SettingsStore
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from agentbase.config import AppPaths

_NOW = "2026-10-01T00:00:00+00:00"
_PIPELINE_IDS = {
    "a7e2c1d0-5b3f-4c6a-9e81-0f4d2b7c9a11",
    "b8f3d2e1-6c4a-4d7b-8f92-1a5e3c8dab22",
    "c9a4e3f2-7d5b-4e8c-9a03-2b6f4d9ebc33",
    "dab5f403-8e6c-4f9d-8b14-3c7a5eafcd44",
    "ebc6a514-9f7d-4a0e-9c25-4d8b6fb0de55",
}
_TOOLS = {
    "market-movers": ["read_prices", "read_file"],
    "portfolio-review": ["compute_portfolio", "read_file", "list_dir", "write_file"],
    "risk-manager": ["check_limits", "read_file", "list_dir", "write_file"],
    "review-analyst": [
        "score_predictions",
        "read_file",
        "list_dir",
        "write_file",
        "propose_memory",
    ],
}
_MIGRATED_AGENT_NAMES = (*_TOOLS, "event-calendar")


def _at_version(app_paths: AppPaths, version: int) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(
        migration for migration in original if migration.version <= version
    )
    database = Database(app_paths.db_path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    assert database.schema_version == version
    return database


def _upgraded(app_paths: AppPaths) -> Database:
    database = Database(app_paths.db_path)
    database.connect()
    assert database.schema_version == LATEST_SCHEMA_VERSION == 23
    return database


def _agents(database: Database) -> dict[str, dict[str, Any]]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT name, system_prompt, allowed_tools, model, updated_at FROM agent_defs"
            " WHERE space_id = ? AND name IN (?, ?, ?, ?, ?)",
            (DEFAULT_SPACE_ID, *_MIGRATED_AGENT_NAMES),
        ).fetchall()
    return {str(row["name"]): dict(row) for row in rows}


def _architects(database: Database) -> dict[str, dict[str, Any]]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT name, system_prompt, allowed_tools, auto_approve, provider, model,"
            " updated_at FROM agent_defs WHERE space_id = ? AND name IN (?, ?)",
            (DEFAULT_SPACE_ID, "bull-architect", "bear-architect"),
        ).fetchall()
    return {str(row["name"]): dict(row) for row in rows}


def _goals(database: Database) -> dict[str, str]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT name, goal FROM schedules WHERE id IN (?, ?, ?, ?, ?)",
            tuple(_PIPELINE_IDS),
        ).fetchall()
    return {str(row["name"]): str(row["goal"]) for row in rows}


def _saved_hosts(database: Database) -> list[str] | None:
    with database.read() as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = 'auto_approve_hosts'"
        ).fetchone()
    return None if row is None else list(json.loads(row["value"]))


def test_a_fresh_database_wires_the_tools_goals_and_new_host_default(
    app_paths: AppPaths,
) -> None:
    database = _upgraded(app_paths)
    try:
        agents = _agents(database)
        assert set(agents) == set(_MIGRATED_AGENT_NAMES)
        for name, tools in _TOOLS.items():
            assert json.loads(agents[name]["allowed_tools"]) == tools, name
        assert "Call read_prices first" in agents["market-movers"]["system_prompt"]
        assert "Call compute_portfolio first" in agents["portfolio-review"]["system_prompt"]
        assert "Call check_limits first" in agents["risk-manager"]["system_prompt"]
        assert "Call score_predictions first" in agents["review-analyst"]["system_prompt"]
        calendar_prompt = agents["event-calendar"]["system_prompt"]
        assert "config/sources.json" in calendar_prompt
        assert "Fetch only the URLs under its events object" in calendar_prompt
        assert "Do not fetch SEC, BLS, FOMC, earnings" in calendar_prompt

        goals = _goals(database)
        assert "If it reports no new session" in goals["Morning collection"]
        assert "write nothing" in goals["Theses and risk"]
        assert "only where raw/filings/{TICKER}/" in goals["Weekly knowledge"]
        assert "score_predictions" in goals["Weekly review"]

        assert _saved_hosts(database) is None
        assert SettingsStore(database)._get_sync().auto_approve_hosts == [
            "news.google.com",
            "query1.finance.yahoo.com",
            "api.fiscaldata.treasury.gov",
        ]
    finally:
        database.close()


def test_an_unused_database_created_since_019_gets_the_new_hosts(
    app_paths: AppPaths,
) -> None:
    before = _at_version(app_paths, 20)
    try:
        with before.read() as connection:
            schedule_ids = {
                str(row["id"]) for row in connection.execute("SELECT id FROM schedules")
            }
        assert schedule_ids == _PIPELINE_IDS
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        assert _saved_hosts(after) is None
        assert SettingsStore(after)._get_sync().auto_approve_hosts[-2:] == [
            "query1.finance.yahoo.com",
            "api.fiscaldata.treasury.gov",
        ]
    finally:
        after.close()


def test_a_used_database_without_a_saved_host_list_gets_the_old_default_pinned(
    app_paths: AppPaths,
) -> None:
    before = _at_version(app_paths, 20)
    try:
        with before.write() as connection:
            connection.execute(
                "INSERT INTO runs (id, space_id, goal, status, origin, created_at)"
                " VALUES ('used', ?, 'g', 'completed', 'ui', ?)",
                (DEFAULT_SPACE_ID, _NOW),
            )
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        assert _saved_hosts(after) == ["news.google.com", "stooq.com"]
        assert SettingsStore(after)._get_sync().auto_approve_hosts == [
            "news.google.com",
            "stooq.com",
        ]
    finally:
        after.close()


def test_021_preserves_edited_prompts_allowlists_goals_and_saved_hosts(
    app_paths: AppPaths,
) -> None:
    before = _at_version(app_paths, 20)
    try:
        with before.write() as connection:
            connection.execute(
                "UPDATE agent_defs SET system_prompt = 'My mover prompt.', updated_at = ?"
                " WHERE name = 'market-movers'",
                (_NOW,),
            )
            connection.execute(
                "UPDATE agent_defs SET system_prompt = 'My calendar prompt.', updated_at = ?"
                " WHERE name = 'event-calendar'",
                (_NOW,),
            )
            connection.execute(
                "UPDATE agent_defs SET allowed_tools = '[\"read_file\"]', updated_at = ?"
                " WHERE name = 'portfolio-review'",
                (_NOW,),
            )
            connection.execute(
                "UPDATE schedules SET goal = 'My collection goal.', updated_at = ?"
                " WHERE name = 'Morning collection'",
                (_NOW,),
            )
            connection.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES"
                " ('auto_approve_hosts', '[\"feeds.example\"]', ?)",
                (_NOW,),
            )
        original_agents = _agents(before)
        original_goals = _goals(before)
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        agents = _agents(after)
        goals = _goals(after)
        assert agents["market-movers"] == original_agents["market-movers"]
        assert agents["event-calendar"] == original_agents["event-calendar"]
        assert agents["portfolio-review"] == original_agents["portfolio-review"]
        assert goals["Morning collection"] == original_goals["Morning collection"]
        assert _saved_hosts(after) == ["feeds.example"]
        assert "Call check_limits first" in agents["risk-manager"]["system_prompt"]
        assert "score_predictions" in agents["review-analyst"]["allowed_tools"]
    finally:
        after.close()


def test_022_repairs_old_shipped_prompts_after_model_only_edits(
    app_paths: AppPaths,
) -> None:
    before = _at_version(app_paths, 20)
    try:
        with before.write() as connection:
            connection.execute(
                "UPDATE agent_defs SET model = 'gpt-5.6-terra', updated_at = ?"
                " WHERE name IN ('market-movers', 'portfolio-review', 'risk-manager',"
                " 'event-calendar', 'review-analyst')",
                (_NOW,),
            )
    finally:
        before.close()

    skipped = _at_version(app_paths, 21)
    try:
        agents = _agents(skipped)
        assert json.loads(agents["market-movers"]["allowed_tools"]) == [
            "http_get",
            "read_file",
            "write_file",
        ]
        assert "read_prices" not in agents["market-movers"]["system_prompt"]
    finally:
        skipped.close()

    repaired = _upgraded(app_paths)
    try:
        agents = _agents(repaired)
        for name in _MIGRATED_AGENT_NAMES:
            assert agents[name]["model"] == "gpt-5.6-terra"
        for name, tools in _TOOLS.items():
            assert json.loads(agents[name]["allowed_tools"]) == tools
        assert "Call read_prices first" in agents["market-movers"]["system_prompt"]
        assert "Call compute_portfolio first" in agents["portfolio-review"]["system_prompt"]
        assert "Call check_limits first" in agents["risk-manager"]["system_prompt"]
        assert "Call score_predictions first" in agents["review-analyst"]["system_prompt"]
        assert (
            "Fetch only the URLs under its events object"
            in agents["event-calendar"]["system_prompt"]
        )
    finally:
        repaired.close()


def test_023_points_the_theses_stage_at_the_session_files_and_an_always_written_file(
    app_paths: AppPaths,
) -> None:
    """Told to use only the movers file, both architects found no evidence id and
    wrote nothing, and check_limits then stopped the chain on the missing file."""
    database = _upgraded(app_paths)
    try:
        goal = _goals(database)["Theses and risk"]
        assert "Use only the movers file" not in goal
        assert "that session's files in raw/ and portfolio/computed.json" in goal
        assert "an empty one when the evidence supports no call" in goal
        architects = _architects(database)
        assert set(architects) == {"bull-architect", "bear-architect"}
        for name, agent in architects.items():
            prompt = agent["system_prompt"]
            assert "- Always write that file." in prompt, name
            assert "dated with the session date of the\nmovers file" in prompt, name
            assert "Writing nothing" not in prompt, name
    finally:
        database.close()


def test_023_upgrades_shipped_theses_text_after_model_only_edits(
    app_paths: AppPaths,
) -> None:
    before = _at_version(app_paths, 22)
    try:
        with before.write() as connection:
            connection.execute(
                "UPDATE agent_defs SET provider = 'openai', model = 'gpt-5.6-terra',"
                " updated_at = ? WHERE name IN ('bull-architect', 'bear-architect')",
                (_NOW,),
            )
        original = _architects(before)
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        for name, agent in _architects(after).items():
            assert "- Always write that file." in agent["system_prompt"], name
            kept = {key: value for key, value in agent.items() if key != "system_prompt"}
            assert kept == {
                key: value for key, value in original[name].items() if key != "system_prompt"
            }, name
    finally:
        after.close()


def test_023_keeps_an_edited_theses_goal_and_architect_prompt(app_paths: AppPaths) -> None:
    before = _at_version(app_paths, 22)
    try:
        with before.write() as connection:
            connection.execute(
                "UPDATE schedules SET goal = 'My theses goal.', updated_at = ?"
                " WHERE name = 'Theses and risk'",
                (_NOW,),
            )
            connection.execute(
                "UPDATE agent_defs SET system_prompt = 'My bull prompt.', updated_at = ?"
                " WHERE name = 'bull-architect'",
                (_NOW,),
            )
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        assert _goals(after)["Theses and risk"] == "My theses goal."
        architects = _architects(after)
        assert architects["bull-architect"]["system_prompt"] == "My bull prompt."
        assert "- Always write that file." in architects["bear-architect"]["system_prompt"]
    finally:
        after.close()
