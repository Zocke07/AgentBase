"""Phase 17's model catalogue and migration 020."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agentbase.providers.catalog import catalog_for, equivalent
from agentbase.providers.pricing import PRICES
from agentbase.store import db as db_module
from agentbase.store.db import LATEST_SCHEMA_VERSION, Database
from agentbase.store.settings import DEFAULT_MODEL, DEFAULT_MODELS
from agentbase.store.spaces import DEFAULT_SPACE_ID

if TYPE_CHECKING:
    from agentbase.config import AppPaths

_NOW = "2026-09-30T00:00:00+00:00"
_SONNET_AGENT_IDS = {
    "0cdfe6c1-4f35-47a6-99d1-f92952984df4",
    "6dcd4865-b830-42fe-b005-cca3f9d1057a",
    "cc55c979-8117-4b68-b9ea-83d4435e1823",
    "714a2fec-4ddf-4583-922e-833b6abd4fd4",
    "8995be58-7f43-4292-a52f-3b8ee8b533a6",
}


def _at_version_19(app_paths: AppPaths) -> Database:
    original = db_module.MIGRATIONS
    db_module.MIGRATIONS = tuple(migration for migration in original if migration.version <= 19)
    database = Database(app_paths.db_path)
    try:
        database.connect()
    finally:
        db_module.MIGRATIONS = original
    assert database.schema_version == 19
    return database


def _upgraded(app_paths: AppPaths) -> Database:
    database = Database(app_paths.db_path)
    database.connect()
    assert database.schema_version == LATEST_SCHEMA_VERSION == 20
    return database


def _space_model(database: Database, space_id: str = DEFAULT_SPACE_ID) -> str | None:
    with database.read() as connection:
        row = connection.execute(
            "SELECT model FROM spaces WHERE id = ?", (space_id,)
        ).fetchone()
    assert row is not None
    value = row["model"]
    return str(value) if value is not None else None


def _models(database: Database) -> dict[str, tuple[str | None, str, str]]:
    with database.read() as connection:
        rows = connection.execute(
            "SELECT id, model, created_at, updated_at FROM agent_defs"
            " WHERE id IN (?, ?, ?, ?, ?)",
            tuple(_SONNET_AGENT_IDS),
        ).fetchall()
    return {
        str(row["id"]): (row["model"], str(row["created_at"]), str(row["updated_at"]))
        for row in rows
    }


def test_sonnet_5_5_is_priced_current_and_balanced() -> None:
    price = PRICES["claude-sonnet-5-5"]
    assert (price.input_micros_per_million, price.output_micros_per_million) == (
        2_000_000,
        10_000_000,
    )
    entries = {entry.model: entry for entry in catalog_for("anthropic")}
    assert (entries["claude-sonnet-5-5"].tier, entries["claude-sonnet-5-5"].current) == (
        "balanced",
        True,
    )
    assert entries["claude-sonnet-5"].current is False


def test_each_provider_has_its_own_space_default_and_untiered_models_use_it() -> None:
    assert DEFAULT_MODEL == "claude-sonnet-5-5"
    assert DEFAULT_MODELS == {
        "anthropic": "claude-sonnet-5-5",
        "openai": "gpt-6-sol",
        "ollama": None,
    }
    assert equivalent("unlisted", "ollama", "anthropic") == "claude-sonnet-5-5"
    assert equivalent("unlisted", "ollama", "openai") == "gpt-6-sol"


def test_a_fresh_database_starts_on_sonnet_5_5_without_pinning_the_old_default(
    app_paths: AppPaths,
) -> None:
    database = _upgraded(app_paths)
    try:
        assert _space_model(database) == "claude-sonnet-5-5"
        assert {model for model, _, _ in _models(database).values()} == {"claude-sonnet-5-5"}
        with database.read() as connection:
            saved = connection.execute(
                "SELECT value FROM settings WHERE key = 'model'"
            ).fetchone()
        assert saved is None
    finally:
        database.close()


def test_an_unused_database_created_since_019_ignores_the_five_seeded_schedules(
    app_paths: AppPaths,
) -> None:
    before = _at_version_19(app_paths)
    try:
        with before.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM schedules").fetchone()[0] == 5
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        assert _space_model(after) == "claude-sonnet-5-5"
    finally:
        after.close()


def test_a_used_database_keeps_its_spaces_and_gets_the_old_setting_pinned(
    app_paths: AppPaths,
) -> None:
    before = _at_version_19(app_paths)
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
        assert _space_model(after) == "claude-opus-5-5"
        with after.read() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = 'model'"
            ).fetchone()
        assert row is not None and json.loads(row["value"]) == "claude-opus-5-5"
        assert {model for model, _, _ in _models(after).values()} == {"claude-sonnet-5-5"}
    finally:
        after.close()


def test_020_preserves_edited_agents_and_every_existing_nondefault_space(
    app_paths: AppPaths,
) -> None:
    before = _at_version_19(app_paths)
    edited_id = "0cdfe6c1-4f35-47a6-99d1-f92952984df4"
    try:
        with before.write() as connection:
            connection.execute(
                "UPDATE agent_defs SET role = 'My librarian', updated_at = ? WHERE id = ?",
                (_NOW, edited_id),
            )
            connection.execute(
                "INSERT INTO spaces (id, name, provider, model, created_at, updated_at)"
                " VALUES ('lab', 'Lab', 'anthropic', 'claude-opus-5-5', ?, ?)",
                (_NOW, _NOW),
            )
        original = _models(before)
    finally:
        before.close()

    after = _upgraded(app_paths)
    try:
        models = _models(after)
        assert models[edited_id][0] == "claude-sonnet-5"
        assert models[edited_id][1:] == original[edited_id][1:]
        assert all(
            model == "claude-sonnet-5-5"
            for agent_id, (model, _, _) in models.items()
            if agent_id != edited_id
        )
        assert _space_model(after) == "claude-opus-5-5"
        assert _space_model(after, "lab") == "claude-opus-5-5"
    finally:
        after.close()
