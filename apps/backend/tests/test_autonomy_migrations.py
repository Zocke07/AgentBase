"""Migrations that make autonomy the default without moving an upgraded install.

Each test builds a database at the version before the migration, fills it the
way a real install would be, and opens it with the full migration list.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.settings import SettingsStore
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from agentbase.config import AppPaths

_NOW = "2026-09-28T00:00:00+00:00"


def _at_version(app_paths: AppPaths, version: int) -> Database:
    """A connected database migrated only as far as ``version``."""
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(m for m in original if m.version <= version)
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
    assert database.schema_version == LATEST_SCHEMA_VERSION
    return database


def _settings_rows(database: Database) -> dict[str, Any]:
    with database.read() as connection:
        return {
            row["key"]: json.loads(row["value"])
            for row in connection.execute("SELECT key, value FROM settings")
        }


def _put_settings(database: Database, values: dict[str, Any]) -> None:
    with database.write() as connection:
        connection.executemany(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            [(key, json.dumps(value), _NOW) for key, value in values.items()],
        )


# --- migration 017: high risk is never answered by policy ---------------------


def test_017_strips_high_risk_answers_and_keeps_the_rest(app_paths: AppPaths) -> None:
    sixteen = _at_version(app_paths, 16)
    try:
        _put_settings(
            sixteen,
            {
                "auto_approve": ["low", "high"],
                "tool_policies": {"run_shell": "allow", "write_file": "allow"},
            },
        )
        with sixteen.write() as connection:
            connection.execute(
                "INSERT INTO spaces (id, name, auto_approve, tool_policies, created_at, updated_at)"
                " VALUES ('lab', 'Lab', ?, ?, ?, ?)",
                (
                    json.dumps(["high", "medium"]),
                    json.dumps({"run_shell": "allow", "read_file": "deny"}),
                    _NOW,
                    _NOW,
                ),
            )
            connection.execute(
                "INSERT INTO spaces (id, name, auto_approve, tool_policies, created_at, updated_at)"
                " VALUES ('quiet', 'Quiet', NULL, ?, ?, ?)",
                (json.dumps({"run_shell": "deny"}), _NOW, _NOW),
            )
    finally:
        sixteen.close()

    upgraded = _upgraded(app_paths)
    try:
        rows = _settings_rows(upgraded)
        assert rows["auto_approve"] == ["low"]
        assert rows["tool_policies"] == {"write_file": "allow"}
        with upgraded.read() as connection:
            spaces = {
                row["id"]: row
                for row in connection.execute(
                    "SELECT id, auto_approve, tool_policies FROM spaces"
                )
            }
        assert json.loads(spaces["lab"]["auto_approve"]) == ["medium"]
        assert json.loads(spaces["lab"]["tool_policies"]) == {"read_file": "deny"}
        # Inheriting stays inheriting, and a refusal of the shell stays.
        assert spaces["quiet"]["auto_approve"] is None
        assert json.loads(spaces["quiet"]["tool_policies"]) == {"run_shell": "deny"}
        # The stricter model reads what the migration left.
        settings = SettingsStore(upgraded)._get_sync()
        assert [str(level) for level in settings.auto_approve] == ["low"]
    finally:
        upgraded.close()


# --- migration 018: autonomy is the default for fresh installs only ------------
#
# Settings store only the keys someone saved and fill the rest from code, so a
# new default would silently change every upgraded install. 018 pins the old
# answers into any database that has been used; a fresh one keeps none.

_PINNED = {
    "auto_approve": [],
    "auto_approve_hosts": ["*"],
    "channel_approvals": "dashboard_only",
}


def _used(database: Database, how: str) -> None:
    with database.write() as connection:
        if how == "a run":
            connection.execute(
                "INSERT INTO runs (id, space_id, goal, status, origin, created_at)"
                " VALUES ('r1', ?, 'g', 'completed', 'ui', ?)",
                (DEFAULT_SPACE_ID, _NOW),
            )
        elif how == "a saved setting":
            connection.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('provider', ?, ?)",
                (json.dumps("openai"), _NOW),
            )
        elif how == "a schedule":
            connection.execute(
                "INSERT INTO schedules (id, space_id, name, goal, cadence, created_at, updated_at)"
                " VALUES ('s1', ?, 'n', 'g', ?, ?, ?)",
                (DEFAULT_SPACE_ID, json.dumps({"kind": "daily", "at": "09:00"}), _NOW, _NOW),
            )
        elif how == "a space of its own":
            connection.execute(
                "INSERT INTO spaces (id, name, created_at, updated_at)"
                " VALUES ('lab', 'Lab', ?, ?)",
                (_NOW, _NOW),
            )


@pytest.mark.parametrize(
    "how", ["a run", "a saved setting", "a schedule", "a space of its own"]
)
def test_018_keeps_a_used_install_asking_as_it_did(app_paths: AppPaths, how: str) -> None:
    seventeen = _at_version(app_paths, 17)
    try:
        _used(seventeen, how)
    finally:
        seventeen.close()

    upgraded = _upgraded(app_paths)
    try:
        rows = _settings_rows(upgraded)
        for key, value in _PINNED.items():
            assert rows[key] == value, key
        settings = SettingsStore(upgraded)._get_sync()
        assert settings.auto_approve == []
        assert settings.auto_approve_hosts == ["*"]
        assert settings.channel_approvals == "dashboard_only"
    finally:
        upgraded.close()


def test_018_leaves_an_answer_someone_already_saved(app_paths: AppPaths) -> None:
    seventeen = _at_version(app_paths, 17)
    try:
        _put_settings(seventeen, {"auto_approve": ["low"], "channel_approvals": "originator"})
    finally:
        seventeen.close()

    upgraded = _upgraded(app_paths)
    try:
        rows = _settings_rows(upgraded)
        assert rows["auto_approve"] == ["low"]
        assert rows["channel_approvals"] == "originator"
        assert rows["auto_approve_hosts"] == ["*"]
    finally:
        upgraded.close()


def test_a_fresh_install_starts_autonomous(app_paths: AppPaths) -> None:
    fresh = _upgraded(app_paths)
    try:
        assert _settings_rows(fresh) == {}
        settings = SettingsStore(fresh)._get_sync()
        assert [str(level) for level in settings.auto_approve] == ["low", "medium"]
        assert settings.auto_approve_hosts == [
            "news.google.com",
            "query1.finance.yahoo.com",
            "feeds.finance.yahoo.com",
            "www.sec.gov",
            "data.sec.gov",
            "api.fiscaldata.treasury.gov",
        ]
        assert settings.channel_approvals == "originator"
        assert settings.tool_policies == {}
    finally:
        fresh.close()


# --- migration 019: the shipped examples run as a pipeline ----------------------

_PIPELINE: dict[str, dict[str, Any]] = {
    "Morning collection": {"kind": "weekly", "at": "07:00", "weekdays": [1, 2, 3, 4, 5]},
    "Theses and risk": {"kind": "after", "follows": "Morning collection"},
    "Daily decision": {"kind": "after", "follows": "Theses and risk"},
    "Weekly knowledge": {"kind": "weekly", "at": "09:00", "weekdays": [5]},
    "Weekly review": {"kind": "weekly", "at": "18:00", "weekdays": [6]},
}

_WIDENED = ("bull-architect", "bear-architect", "risk-manager", "decision", "review-analyst")


def _schedules(database: Database) -> dict[str, dict[str, Any]]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT id, space_id, name, goal, cadence, enabled, next_run_at, max_run_seconds"
            " FROM schedules"
        ).fetchall()
    return {row["name"]: {**dict(row), "cadence": json.loads(row["cadence"])} for row in rows}


def _levels(database: Database, name: str) -> list[str]:
    with database.read() as connection:
        row = connection.execute(
            "SELECT auto_approve FROM agent_defs WHERE space_id = ? AND name = ?",
            (DEFAULT_SPACE_ID, name),
        ).fetchone()
    return list(json.loads(row["auto_approve"]))


def test_a_fresh_install_ships_the_pipeline_switched_off(app_paths: AppPaths) -> None:
    fresh = _upgraded(app_paths)
    try:
        schedules = _schedules(fresh)
        assert set(schedules) == set(_PIPELINE)
        ids = {name: row["id"] for name, row in schedules.items()}
        for name, cadence in _PIPELINE.items():
            row = schedules[name]
            assert row["space_id"] == DEFAULT_SPACE_ID
            # Nothing spends until someone turns it on.
            assert row["enabled"] == 0 and row["next_run_at"] is None, name
            assert row["max_run_seconds"] == 1800, name
            if cadence["kind"] == "after":
                assert row["cadence"] == {
                    "kind": "after",
                    "schedule_id": ids[str(cadence["follows"])],
                }
            else:
                assert row["cadence"] == cadence, name
        # The whole morning collection fits one run: the supervisor and four workers.
        morning = schedules["Morning collection"]["goal"]
        for agent in ("news-scanner", "market-movers", "event-calendar", "portfolio-review"):
            assert agent in morning
        assert "person" in schedules["Daily decision"]["goal"]
        for name in _WIDENED:
            assert _levels(fresh, name) == ["low", "medium"], name
    finally:
        fresh.close()


def test_019_widens_only_untouched_stages_and_seeds_only_what_the_roster_can_run(
    app_paths: AppPaths,
) -> None:
    eighteen = _at_version(app_paths, 18)
    try:
        with eighteen.write() as connection:
            # Someone narrowed the bear themselves, and deleted the decision agent.
            connection.execute(
                "UPDATE agent_defs SET allowed_tools = ? WHERE space_id = ? AND name = ?",
                (json.dumps(["read_file", "write_file"]), DEFAULT_SPACE_ID, "bear-architect"),
            )
            connection.execute(
                "DELETE FROM agent_defs WHERE space_id = ? AND name = 'decision'",
                (DEFAULT_SPACE_ID,),
            )
            connection.execute(
                "UPDATE agent_defs SET role = 'My own scanner.' WHERE name = 'news-scanner'"
            )
    finally:
        eighteen.close()

    upgraded = _upgraded(app_paths)
    try:
        assert _levels(upgraded, "bull-architect") == ["low", "medium"]
        assert _levels(upgraded, "bear-architect") == ["low"]
        schedules = _schedules(upgraded)
        assert "Daily decision" not in schedules
        assert {"Morning collection", "Theses and risk", "Weekly review"} <= set(schedules)
        with upgraded.read() as connection:
            role = connection.execute(
                "SELECT role FROM agent_defs WHERE name = 'news-scanner'"
            ).fetchone()["role"]
        assert role == "My own scanner."
    finally:
        upgraded.close()


def test_the_scanner_is_described_as_what_it_now_reads(app_paths: AppPaths) -> None:
    fresh = _upgraded(app_paths)
    try:
        with fresh.read() as connection:
            role = connection.execute(
                "SELECT role FROM agent_defs WHERE name = 'news-scanner'"
            ).fetchone()["role"]
        assert role == (
            "Collects public news about watchlist tickers into a fixed schema. "
            "Performs no analysis."
        )
    finally:
        fresh.close()
