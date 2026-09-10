"""Shared fixtures.

The async tests run on anyio's pytest plugin rather than pytest-asyncio.
anyio is already in the tree underneath Starlette, and it is what Starlette's
own test client uses, so this adds a declared dependency rather than a new
package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agentspace.budget.ledger import BudgetLedger
from agentspace.config import AppPaths
from agentspace.events.bus import EventBus
from agentspace.events.store import EventStore
from agentspace.secrets import SecretStore
from agentspace.store.agents import AgentDefStore
from agentspace.store.db import Database
from agentspace.store.settings import SettingsStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every test's data directory at `tmp_path`.

    Autouse, and deliberately not optional. `create_app()` with no explicit
    paths falls back to `resolve_app_paths()`, which consults this variable and
    then the real OS app-data directory — so a test that builds an app without
    passing paths opens a database on the developer's actual machine. That is
    not hypothetical: it is how a stray `agentspace.sqlite3` came to sit inside
    the installed application's directory during Phase 2.

    Tests that need a specific directory take the `app_paths` fixture and pass
    it explicitly; this only decides where the *unconfigured* path leads.
    """
    monkeypatch.setenv("AGENTSPACE_DATA_DIR", str(tmp_path / "data-dir-fallback"))


@pytest.fixture
def anyio_backend() -> str:
    """Run `@pytest.mark.anyio` tests on asyncio only; we do not ship trio."""
    return "asyncio"


@pytest.fixture
def app_paths(tmp_path: Path) -> AppPaths:
    """An isolated data directory, laid out exactly as the real one."""
    paths = AppPaths(
        data_dir=tmp_path,
        db_path=tmp_path / "agentspace.sqlite3",
        logs_dir=tmp_path / "logs",
        workspace_root=tmp_path / "workspace",
    )
    paths.ensure_exists()
    return paths


@pytest.fixture
def db(app_paths: AppPaths) -> Iterator[Database]:
    """A connected, migrated database that is closed before tmp_path is torn down.

    Closing matters on Windows: an open SQLite handle keeps the file locked and
    makes pytest's tmp_path cleanup fail with a PermissionError that has nothing
    to do with the test.
    """
    database = Database(app_paths.db_path)
    database.connect()
    try:
        yield database
    finally:
        database.close()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def store(db: Database, bus: EventBus) -> EventStore:
    return EventStore(db, bus)


# --- the workspace stores ----------------------------------------------------
#
# Phase 4 defined these locally in `test_orchestrator.py`. Phase 5 added a
# second and a third module that drive runs, and three copies of the same
# four-line fixture is three places to forget when a store grows a dependency.


@pytest.fixture
def settings(db: Database) -> SettingsStore:
    return SettingsStore(db)


@pytest.fixture
def agents(db: Database, settings: SettingsStore) -> AgentDefStore:
    """The agent registry, seeded with the built-ins by migration 003."""
    return AgentDefStore(db, settings)


@pytest.fixture
def ledger(db: Database, store: EventStore, settings: SettingsStore) -> BudgetLedger:
    return BudgetLedger(db, settings, store)


@pytest.fixture
def secrets() -> SecretStore:
    return SecretStore()
