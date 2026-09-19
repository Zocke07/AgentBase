"""Migration 010: the default space ships the investment roster.

A fresh install's default roster is the ten definitions; an upgrade adds
them beside what the user already has, retires the untouched generic roles
and leaves an edited one in place, deletable.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

import pytest

import agentspace.store.db as db_module
from agentspace.store.db import LATEST_SCHEMA_VERSION, Database
from agentspace.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from agentspace.config import AppPaths

#: What 010 seeds: name, model, allowed tools, step ceiling, narrowed levels.
ROSTER: Final[dict[str, tuple[str, tuple[str, ...], int, tuple[str, ...]]]] = {
    "news-scanner": ("claude-haiku-4-5", ("http_get", "write_file"), 20, ("low", "medium")),
    "research-librarian": (
        "claude-sonnet-5",
        ("read_file", "list_dir", "search_knowledge", "write_file", "propose_memory"),
        20,
        ("low", "medium"),
    ),
    "market-movers": (
        "claude-haiku-4-5",
        ("http_get", "read_file", "write_file"),
        12,
        ("low", "medium"),
    ),
    "event-calendar": (
        "claude-haiku-4-5",
        ("http_get", "read_file", "write_file"),
        12,
        ("low", "medium"),
    ),
    "portfolio-review": (
        "claude-haiku-4-5",
        ("read_file", "list_dir", "write_file"),
        8,
        ("low", "medium"),
    ),
    "bull-architect": (
        "claude-sonnet-5",
        ("read_file", "list_dir", "search_knowledge", "write_file"),
        12,
        ("low",),
    ),
    "bear-architect": (
        "claude-sonnet-5",
        ("read_file", "list_dir", "search_knowledge", "write_file"),
        12,
        ("low",),
    ),
    "risk-manager": ("claude-sonnet-5", ("read_file", "list_dir", "write_file"), 10, ("low",)),
    "decision": ("claude-opus-5", ("read_file", "list_dir", "write_file"), 8, ("low",)),
    "review-analyst": (
        "claude-sonnet-5",
        ("read_file", "list_dir", "write_file", "propose_memory"),
        15,
        ("low",),
    ),
}

RESEARCHER_ID: Final[str] = "b6a1f0d2-8c34-4e59-9f27-1a5d3c7e40b1"
WRITER_ID: Final[str] = "d41b7e58-2f96-4a03-8b6c-9e2d5a1f7c34"
REVIEWER_ID: Final[str] = "f0927c14-6b8d-4e71-a53f-2c9814d6b0ae"


def _roster(
    database: Database, space_id: str = DEFAULT_SPACE_ID
) -> dict[str, dict[str, object]]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT id, name, provider, model, allowed_tools, max_steps, auto_approve,"
            " is_builtin, enabled, system_prompt FROM agent_defs WHERE space_id = ?"
            " ORDER BY name",
            (space_id,),
        ).fetchall()
    return {str(row["name"]): dict(row) for row in rows}


def test_a_fresh_install_ships_the_investment_roster_as_its_built_ins(db: Database) -> None:
    roster = _roster(db)

    assert set(roster) == set(ROSTER)
    for name, (model, tools, steps, levels) in ROSTER.items():
        row = roster[name]
        assert row["provider"] == "anthropic", name
        assert row["model"] == model, name
        assert tuple(json.loads(str(row["allowed_tools"]))) == tools, name
        assert row["max_steps"] == steps, name
        assert tuple(json.loads(str(row["auto_approve"]))) == levels, name
        assert row["is_builtin"] == 1 and row["enabled"] == 1, name


def test_nothing_seeded_can_run_a_shell_and_only_collectors_fetch(db: Database) -> None:
    """The safety property behind the prompts: the agents that read untrusted
    pages get no shell, and nothing else reaches the network."""
    roster = _roster(db)

    fetchers = {name for name, row in roster.items() if "http_get" in str(row["allowed_tools"])}
    assert fetchers == {"news-scanner", "market-movers", "event-calendar"}
    assert not any("run_shell" in str(row["allowed_tools"]) for row in roster.values())
    # Narrowing only: no seeded row names a level the app-wide policy has not
    # enabled, and none skips the dialog for a high-risk call.
    assert not any("high" in str(row["auto_approve"]) for row in roster.values())


def test_the_bear_mirrors_the_bull(db: Database) -> None:
    roster = _roster(db)
    bull = str(roster["bull-architect"]["system_prompt"])
    bear = str(roster["bear-architect"]["system_prompt"])

    assert "RISE over 1, 3, 5 and 7 trading days" in bull
    assert "FALL over 1, 3, 5 and 7 trading days" in bear
    assert '"direction": "up"' in bull and '"direction": "down"' in bear
    assert "theses/bull-{YYYY-MM-DD}.jsonl" in bull and "theses/bear-{YYYY-MM-DD}.jsonl" in bear
    assert "Do not read theses/bear-*" in bull and "Do not read theses/bull-*" in bear


def _at_version_nine(app_paths: AppPaths) -> Database:
    """A database migrated through 009 only, as a 0.4.0 install left it."""
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(m for m in original if m.version <= 9)
    database = Database(app_paths.db_path)
    try:
        database.connect()
        assert database.schema_version == 9
    finally:
        db_module.MIGRATIONS = original
    return database


def test_an_upgrade_keeps_what_the_user_changed_and_retires_the_rest(
    app_paths: AppPaths,
) -> None:
    before = _at_version_nine(app_paths)
    try:
        with before.write() as connection:
            # The writer was edited; the researcher and reviewer were not.
            connection.execute(
                "UPDATE agent_defs SET system_prompt = 'You write haiku.' WHERE id = ?",
                (WRITER_ID,),
            )
            # The user already has a `decision` agent of their own.
            connection.execute(
                "INSERT INTO agent_defs (id, space_id, name, role, system_prompt,"
                " allowed_tools, max_steps, auto_approve, is_builtin, enabled,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "mine",
                    DEFAULT_SPACE_ID,
                    "decision",
                    "Mine",
                    "Decide my way.",
                    "[]",
                    20,
                    "[]",
                    0,
                    1,
                    "2026-09-01T00:00:00+00:00",
                    "2026-09-01T00:00:00+00:00",
                ),
            )
    finally:
        before.close()

    after = Database(app_paths.db_path)
    after.connect()
    try:
        assert after.schema_version == LATEST_SCHEMA_VERSION
        roster = _roster(after)
    finally:
        after.close()

    assert "researcher" not in roster and "reviewer" not in roster
    writer = roster["writer"]
    assert writer["system_prompt"] == "You write haiku."
    assert writer["is_builtin"] == 0, "an edited generic role is the user's, and deletable"
    mine = roster["decision"]
    assert mine["id"] == "mine" and mine["system_prompt"] == "Decide my way."
    assert set(roster) == (set(ROSTER) | {"writer"})


def test_an_untouched_generic_role_moved_elsewhere_stays_and_becomes_deletable(
    app_paths: AppPaths,
) -> None:
    before = _at_version_nine(app_paths)
    try:
        with before.write() as connection:
            connection.execute(
                "INSERT INTO spaces (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("lab", "Lab", "2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
            )
            connection.execute(
                "UPDATE agent_defs SET space_id = 'lab' WHERE id = ?", (RESEARCHER_ID,)
            )
    finally:
        before.close()

    after = Database(app_paths.db_path)
    after.connect()
    try:
        lab = _roster(after, "lab")
    finally:
        after.close()

    assert list(lab) == ["researcher"]
    assert lab["researcher"]["is_builtin"] == 0


@pytest.mark.parametrize("name", sorted(ROSTER))
def test_every_seeded_prompt_names_where_it_reads_or_writes(db: Database, name: str) -> None:
    """Each prompt is written around the workspace layout; a prompt that lost
    its paths in transit would be an agent with nowhere to work."""
    prompt = str(_roster(db)[name]["system_prompt"])
    assert any(
        folder in prompt
        for folder in (
            "raw/",
            "knowledge/",
            "portfolio/",
            "theses/",
            "risk/",
            "decisions/",
            "scores/",
        )
    )
    assert "—" not in prompt
